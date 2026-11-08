# Databricks notebook source
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

ENDPOINT_NAME = "jetoncount-estimator"

endpoint = w.serving_endpoints.get(ENDPOINT_NAME)

print("Endpoint:", endpoint.name)
print("Ready:", endpoint.state.ready)
print("Config update:", endpoint.state.config_update)

for entity in endpoint.config.served_entities:
    print("Model:", entity.entity_name)
    print("Version:", entity.entity_version)

# COMMAND ----------

long_text = (
    "The city council met on Tuesday to discuss the new transit plan, "
    "which would add three bus lines and extend service hours into the "
    "late evening for residents on the east side. Researchers found "
    "that regular exercise improved memory in older adults, although "
    "the effect depended on how often participants trained and how "
    "long the study lasted."
)

result = w.serving_endpoints.query(
    name=ENDPOINT_NAME,
    dataframe_records=[
        {"text": "Hello world"},
        {"text": ""},
        {"text": long_text}
    ]
)

print(result)

# COMMAND ----------

def predict_tokens(text):

    result = w.serving_endpoints.query(
        name=ENDPOINT_NAME,
        dataframe_records=[
            {"text": text}
        ]
    )

    return result.predictions[0]


prediction = predict_tokens("Hello world")

print("Estimated tokens:", prediction["estimated_tokens"])
print("Method:", prediction["method"])
print("Approximate:", prediction["approximate"])