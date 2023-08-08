import logging
import json

import os
import requests

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

def get_kubernetes_token():
    token_file = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    with open(token_file, "r") as f:
        return f.read().strip()
    
def get_pod_name():
    return os.environ.get("POD_NAME")

def get_container_name():
    return os.environ.get("CONTAINER_NAME", "your-container-name")

# Use this to list pods
def get_pods():
    token = get_kubernetes_token()
    print(f"XXX KUBERNETES_SERVICE_HOST Environment var: {os.environ.get('KUBERNETES_SERVICE_HOST')}")
    api_server = "https://kubernetes.default.svc"
    api_url = f"{api_server}/api/v1/pods"

    print(f"kubernetes token: {get_kubernetes_token()}")
    print(f"pd name: {get_pod_name()}")
    print(f"container name: {get_container_name()}")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    response = requests.get(api_url, headers=headers, verify=False)

    if response.status_code == 200:
        return f"{response.json()}"
    else:
        return f"Error: {response.status_code}, {response.text}"

# Use this to run custom commands
def run_kubectl_command_in_pod(namespace, command):
    # api_server = os.environ.get("KUBERNETES_SERVICE_HOST", "https://kubernetes.default.svc")
    api_server = "https://kubernetes.default.svc"
    api_url = f"{api_server}/api/v1/namespaces/{namespace}/pods/{get_pod_name()}/exec"

    print(f"kubernetes token: {get_kubernetes_token()}")
    print(f"pod name: {get_pod_name()}")
    print(f"container name: {get_container_name()}")
    print(f"command: '{command}'")

    headers = {
        "Authorization": f"Bearer {get_kubernetes_token()}",
        "Content-Type": "application/json"
    }

    data = {
        "apiVersion": "v1",
        "kind": "Exec",
        "metadata": {
            "namespace": namespace,
            "name": get_pod_name(),
        },
        "spec": {
            "container": get_container_name(),
            "command": command.split(' '),
            "stdin": False,
            "tty": False,
        }
    }

    response = requests.post(api_url, headers=headers, json=data, stream=True, verify=False)

    if response.status_code == 200:
        return f"{response.json()}"
    else:
        return f"Error: {response.status_code}, {response.text}"


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
                 "content": f"Can you analyze the alert and make a kubectl command to resolve the alert? Provide only the command, no explanation!\n{params.search_term}"}
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
                logging.error(f"Got no ChatGPT response!")

    except Exception as e:
        answers.append(f"Error calling ChatCompletion.create: {e}")
        raise
    
    return answers


@action
def chat_gpt_enricher(alert: PrometheusKubernetesAlert, params: ChatGPTTokenParams):
    """
    Add a button to the alert - clicking it will ask chat gpt to help find a solution.
    """
    pods = get_pods()
    # pods = run_kubectl_command_in_pod("default", "kubectl get pods -A")

    search_term = ", ".join([f"{key}: {value}" for key, value in alert.alert.labels.items()])
    search_term = f"{search_term}\n{alert.get_title()}\n{alert.get_description()}\nPods: {pods}"
    # search_term = json.dumps(alert.alert, indent=1)
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
