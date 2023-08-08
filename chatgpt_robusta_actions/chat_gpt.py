import logging
import json

import cachetools
import openai
from openai.openai_object import OpenAIObject
from robusta.api import *

cache_size = 100
lru_cache = cachetools.LRUCache(maxsize=cache_size)


class ChatGPTTokenParams(ActionParams):
    azure_openai_token: str
    azure_openai_api_base: str
    azure_openai_deployment_id: str


class ChatGPTParams(ChatGPTTokenParams):
    """
    :var search_term: ChatGPT search term
    :var model: ChatGPT OpenAi API model
    """
    search_term: str
    model: str = "gpt-3.5-turbo"


def query_chatgtp(params: ChatGPTParams):
    openai.api_type = "azure"
    openai.api_base = params.azure_openai_api_base
    openai.api_version = "2023-05-15"
    openai.api_key = params.azure_openai_token
    deployment_id = params.azure_openai_deployment_id

    print(f"ChatGPT search term: {params.search_term}")

    answers = []
    try:
        if params.search_term in lru_cache:
            answers = lru_cache[params.search_term]
        else:
            input = [
                {"role": "system", "content": "You are a helpful assistant. Provide kubectl commands only, no explanations!"},
                {"role": "system", "content": "Provide a runnable kubectl command without placeholders!"},
                {"role": "user",
                 "content": f"Can you analyze the alert and make a Kubernetes command to solve it? Provide only the command, no explanation!\n{params.search_term}"}
            ]

            print(f"ChatGPT input: {input}")
            res: OpenAIObject = openai.ChatCompletion.create(
                deployment_id=deployment_id,
                model=params.model,
                messages=input,
                max_tokens=1000,
                temperature=0
            )
            if res:
                print(f"ChatGPT response: {res}")
                response_content = res.choices[0].message.content
                # Store only the main response in the cache
                lru_cache[params.search_term] = [response_content]
                answers.append(response_content)
            else:
                logging.error(f"Got no Bedrock response!")

    except Exception as e:
        answers.append(f"Error calling ChatCompletion.create: {e}")
        raise
    
    return answers


@action
def chat_gpt_enricher(alert: PrometheusKubernetesAlert, params: ChatGPTTokenParams):
    """
    Add a button to the alert - clicking it will ask chat gpt to help find a solution.
    """

    # search_term = ", ".join([f"{key}: {value}" for key, value in alert.alert.labels.items()])
    search_term = json.dumps(alert.alert, indent=1)
    print ('XXX')
    print("XXX Labels: ", search_term)

    # TODO: dump funktioniert nicht
    # alert_name = json.dumps(alert)

    if not search_term:
        return

    action_params = ChatGPTParams(
        search_term=f"{search_term}",
        azure_openai_token=params.azure_openai_token,
        azure_openai_api_base=params.azure_openai_api_base,
        azure_openai_deployment_id=params.azure_openai_deployment_id
    )

    answers = query_chatgtp(action_params)

    alert.add_enrichment(
        [
            MarkdownBlock(json.dumps(answers))
        ]
    )
