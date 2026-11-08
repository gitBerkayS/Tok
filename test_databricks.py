import os
import requests

url = (
    os.environ["DATABRICKS_HOST"]
    + "/serving-endpoints/"
    + os.environ["DATABRICKS_ENDPOINT"]
    + "/invocations"
)

response = requests.post(
    url,
    headers={
        "Authorization": "Bearer " + os.environ["DATABRICKS_TOKEN"],
        "Content-Type": "application/json",
    },
    json={
        "dataframe_records": [
            {"text": "Hello, this is a test of JetonCount."}
        ]
    },
    timeout=120,
)

print("Status:", response.status_code)
print(response.text)