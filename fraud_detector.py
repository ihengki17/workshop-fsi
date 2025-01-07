import json
from datetime import datetime
from confluent_kafka import Consumer, Producer
from confluent_kafka.serialization import SerializationContext, MessageField
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroDeserializer, AvroSerializer
from confluent_kafka.schema_registry.json_schema import JSONDeserializer, JSONSerializer

# Initialize the Kafka config
def read_config():
  # reads the client configuration from client.properties
  # and returns it as a key-value map
  config = {}
  with open("client.properties") as fh:
    for line in fh:
      line = line.strip()
      if len(line) != 0 and line[0] != "#":
        parameter, value = line.strip().split('=', 1)
        config[parameter] = value.strip()
  return config

def read_schema():
    schema_config = {}
    with open("schema.properties") as sp:
     for line in sp:
        if len(line) != 0 and line[0] != "#":
           parameter, value = line.strip().split('=', 1)
           schema_config[parameter] = value.strip()
    return schema_config

class Feature_Set_Key:
    def __init__(self, credit_card_number, average_spending_amount, customer_email):
        self.credit_card_number = credit_card_number
        self.average_spending_amount= average_spending_amount
        self.customer_email=customer_email
class Feature_Set_Value:
    def __init__(self, total_amount, transaction_count, window_end,window_start,credit_card_number=None):
        self.total_amount = total_amount
        self.transaction_count = transaction_count
        self.window_end = window_end
        self.window_start = window_start
        
class Fraud_Transaction:
    def __init__(self, details):
        self.details = details

    def to_dict(self):
        return {
            "details": self.details
        }

FRAUD_TRANSACTION_SCHEMA = """
{
  "connect.name": "workshop.fraudulenttrans",
  "fields": [
    {
      "name": "details",
      "type": "string"
    }
  ],
  "name": "FraudulentTransactions",
  "namespace": "workshop",
  "type": "record"
}
"""

# Configure the schema properties file
schema_config = read_schema()

# Set up Schema Registry client and JSON Serializer
schema_registry_client = SchemaRegistryClient({
  'url': schema_config["schema.registry.url"],
  'basic.auth.user.info':schema_config["schema.registry.username"]+":"+schema_config["schema.registry.password"]
})

avro_serializer = AvroSerializer(schema_registry_client, FRAUD_TRANSACTION_SCHEMA)

def dict_to_feature_set_key(obj, ctx):
    """
    Converts object literal(dict) to a Feature Set Key instance.

    Args:
        ctx (SerializationContext): Metadata pertaining to the serialization operation.
        obj (dict): Object literal(dict)
    """

    if obj is None:
        return None
    
    return Feature_Set_Key(credit_card_number=obj['CREDIT_CARD_NUMBER'],
                        average_spending_amount=obj['AVERAGE_SPENDING_AMOUNT'],
                        customer_email=obj['CUSTOMER_EMAIL'])

def dict_to_feature_set_value(obj, ctx):

    """
    Converts object literal(dict) to a Feature Set instance.

    Args:
        ctx (SerializationContext): Metadata pertaining to the serialization
            operation.
        obj (dict): Object literal(dict)
    """

    if obj is None:
        return None

    return Feature_Set_Value(total_amount=obj['TOTAL_AMOUNT'],
                transaction_count=obj['TRANSACTION_COUNT'],
                window_end=obj['WINDOW_END'],
                window_start=obj['WINDOW_START']
            )

def identify_fraud(total_amount, transaction_count, average_spending):
    # Rule-based fraud detection logic
    # Example rules:
    if transaction_count >= 2 and total_amount > average_spending:  # Excessive number of transactions
        return True
    return False  # Default to not fraudulent

def produce_fraudulent_transaction(producer,credit_card_number,customer_email,amount, timestamp,average_spend,transactions_count):
    try:
      record = Fraud_Transaction(
          details= f"Generate a short alert message to the user informing the transaction with the given details is likely to be fraud. credit card number {credit_card_number} customer {customer_email} total spend {amount}  average spend {average_spend} total number of transactions {transactions_count} time period {timestamp}"
        )
      serialized_record = avro_serializer(record.to_dict(), SerializationContext("fraudulent_transactions", MessageField.VALUE))

      producer.produce('fraudulent_transactions', value=serialized_record)
      producer.flush()
    except Exception as e:
        print(f"Failed to send record to topic: {e}")

def run_fraud_detection(producer,consumer, json_deserializer_value, avro_deserializer_key):
    try:
        while True:
            msg = consumer.poll(1.0)  # Timeout
            if msg is None:
                print("Polling for messages...")
                continue
            if msg.error():
                print("Error: {}".format(msg.error()))
                continue
            
            feature = json_deserializer_value(msg.value(), SerializationContext(msg.topic(),MessageField.VALUE))
            key = avro_deserializer_key(msg.key(), SerializationContext(msg.topic(),MessageField.KEY))

            if feature is not None:
                total_amount = feature.total_amount
                transaction_count = feature.transaction_count
                average_spending = key.average_spending_amount
                time_range = feature.window_start + " to " + feature.window_end
    
                is_fraudulent = identify_fraud(total_amount, transaction_count, average_spending)
                
                if is_fraudulent:
                    produce_fraudulent_transaction(
                        producer=producer,
                        credit_card_number=key.credit_card_number,
                        customer_email=key.customer_email,
                        amount=total_amount,
                        average_spend=average_spending,
                        transactions_count=transaction_count,
                        timestamp=time_range
                    )
                    print(f"Fraud detected for transaction for credit card: {key.credit_card_number} {feature}")
                consumer.commit()
    except KeyboardInterrupt:
        pass
    finally:
        # closes the consumer connection
        consumer.close()

if __name__ == "__main__":
    # Parse the properties file
    config = read_config()
    
    # Setup consumers
    consumer = Consumer(config)
    consumer.subscribe(['FEATURE_SET'])
    schema_str_key = """
    {
  	"connect.name": "io.confluent.ksql.avro_schemas.FeatureSetKey",
  	"fields": [
   	 {
     	 "default": null,
     	 "name": "CREDIT_CARD_NUMBER",
      	 "type": [
        	"null",
        	"string"
      	 ]
    	},
    	{
      	 "default": null,
      	 "name": "CUSTOMER_EMAIL",
      	 "type": [
        	"null",
        	"string"
      	 ]
    	},
    	{
      	 "default": null,
      	 "name": "AVERAGE_SPENDING_AMOUNT",
      	 "type": [
        	"null",
        	"int"
      	 ]
    	}
      ],
      "name": "FeatureSetKey",
      "namespace": "io.confluent.ksql.avro_schemas",
      "type": "record"
     }
    """
    schema_str_value = """
    {
  	"properties": {
   	 "TOTAL_AMOUNT": {
     	 "connect.index": 1,
     	 "oneOf": [
       	 {
      	    "type": "null"
     	   },
      	  {
       	   "connect.type": "int32",
       	   "type": "integer"
       	 }
     	 ]
   	 },
    	"TRANSACTION_COUNT": {
     	 "connect.index": 0,
     	 "oneOf": [
     	   {
       	   "type": "null"
       	 },
    	    {
    	      "connect.type": "int64",
       	   "type": "integer"
     	   }
   	   ]
   	 },
   	 "WINDOW_END": {
     		"connect.index": 3,
     	 	"oneOf": [
     	   	{
      	    		"type": "null"
        		},
        		{
        	  	"type": "string"
        		}
     	 	]
   	 },
    "WINDOW_START": {
      		"connect.index": 2,
      		"oneOf": [
      		  {
     		     "type": "null"
        		},
        		{
       		     "type": "string"
       			 }
     		]
    	 }
  	},
 	 "type": "object"
	}
    """
    
    # Initialize the Kafka producer for fraudulent transactions
    producer = Producer(config)
    
    schema_config = read_schema()

    # Set up Schema Registry client and JSON Serializer
    schema_registry_client = SchemaRegistryClient({
        'url': schema_config["schema.registry.url"],
        'basic.auth.user.info':schema_config["schema.registry.username"]+":"+schema_config["schema.registry.password"]
        })

    # Run the fraud detection consumer
    json_deserializer_value = JSONDeserializer(schema_str_value,
                                         from_dict=dict_to_feature_set_value)
    
    avro_deserializer_key = AvroDeserializer(schema_registry_client,schema_str_key,
                                         from_dict=dict_to_feature_set_key)
    
    run_fraud_detection(producer,consumer,json_deserializer_value, avro_deserializer_key)
