import logging
import json
import requests

import cachetools
from robusta.api import *

cache_size = 100
lru_cache = cachetools.LRUCache(maxsize=cache_size)


class BedrockParameters(ActionParams):
    search_term: str
    model: str = "gpt-3.5-turbo"
    bedrock_token: str
    bedrock_api_base: str
    bedrock_deployment_id: str


def query_bedrock(params: BedrockParameters):
    bedrock_api_base = params.bedrock_api_base
    bedrock_token = params.bedrock_token
    deployment_id = params.bedrock_deployment_id
    search_term = params.search_term

    logging.info(f"Bedrock search term: {search_term}")

    answers = []
    try:
        if search_term in lru_cache:
            answers = lru_cache[search_term]
        else:
            logging.info(f"Bedrock input: {input}")

            # TODO: most likely  these parameters
            url = f"{bedrock_api_base}/{deployment_id}"
            headers = {
                'Content-Type': 'application/json',
                'Authentication': f"Bearer {bedrock_token}"
                }
            data = {'request': f"You are a helpful assistant. Provide kubectl commands only, no explanations! Can you analyze the alert and make a Kubernetes command to solve it? Provide only the command, no explanation!\n{search_term}"}
            # ---------------

            res = requests.post(url, headers=headers, json=data)

            if res:
                logging.info(f"Bedrock response: {res}")
                response_content = res.choices[0].message.content
                lru_cache[params.search_term] = [response_content]
                answers.append(response_content)
            else:
                logging.error(f"Got no Bedrock response!")

    except Exception as e:
        answers.append(f"Error trying to query Bedrock: {e}")
        raise
    
    return answers


@action
def amazon_bedrock_enricher(alert: PrometheusKubernetesAlert, params: BedrockParameters):
    """
    Add a button to the alert - clicking it will ask chat gpt to help find a solution.
    """

    alert_name = alert.alert.labels.get("alertname", "")
    print (alert)
    print ('XXX')
    print(alert.alert)

    if not alert_name:
        return

    action_params = BedrockParameters(
        search_term=f"{alert_name}",
        bedrock_token=params.bedrock_token,
        bedrock_api_base=params.bedrock_api_base,
        bedrock_deployment_id=params.bedrock_deployment_id
    )

    answers = query_bedrock(action_params)

    alert.add_enrichment(
        [
            JsonBlock(json.dumps(answers))
        ]
    )
