import logging
import json
import subprocess

import os
import requests

import cachetools
import openai
from openai.openai_object import OpenAIObject
from robusta.api import *

from .opsGenieAlerting import OpsGenieAlerting


cache_size = 100
lru_cache = cachetools.LRUCache(maxsize=cache_size)
use_cache = False


class ChatGPTTokenParams(ActionParams):
    azure_openai_token: str
    azure_openai_api_base: str
    azure_openai_deployment_id: str
    opsgenie_key: str


class ChatGPTParams(ChatGPTTokenParams):
    """
    :var search_term: ChatGPT search term
    :var model: ChatGPT OpenAi API model
    """
    search_term: str
    # model: str = "gpt-3.5-turbo"
    model: str = "gpt-4"


def get_pods():
    return subprocess.getoutput('kubectl get pods -A')


def query_chatgtp(params: ChatGPTParams, system=[]):
    openai.api_type = "azure"
    openai.api_base = params.azure_openai_api_base
    openai.api_version = "2023-05-15"
    openai.api_key = params.azure_openai_token
    deployment_id = params.azure_openai_deployment_id

    print(f"ChatGPT search term: {params.search_term}")

    answers = []
    try:
        if use_cache and params.search_term in lru_cache:
            answers = lru_cache[params.search_term]
        else:
            input = [
                {"role": "system", "content": "You are a helpful assistant. Provide kubectl commands only, no explanations!"},
                {"role": "system", "content": "Provide a runnable kubectl command without placeholders!"},
                {"role": "system", "content": "Don't provide kubectl commands that do not modify anything, i.e., no kubectl describe."},
                *[{"role": "system", "content": f"Use this as context information: {system_cmd}"}
                    for system_cmd in system],
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


def runKubectlCommand(cmd):
    return subprocess.getoutput(cmd)


@action
def chat_gpt_enricher(alert: PrometheusKubernetesAlert, params: ChatGPTTokenParams):
    pods = get_pods()

    search_term = ", ".join(
        [f"{key}: {value}" for key, value in alert.alert.labels.items()])
    search_term = f"{search_term}\n{alert.get_title()}\n{alert.get_description()}"
    print('XXX')
    print("XXX Labels: ", search_term)

    if not search_term:
        return

    action_params = ChatGPTParams(
        search_term=f"{search_term}",
        azure_openai_token=params.azure_openai_token,
        azure_openai_api_base=params.azure_openai_api_base,
        azure_openai_deployment_id=params.azure_openai_deployment_id,
        opsgenie_key=""
    )

    answers = query_chatgtp(action_params, [pods])

    kubectlResponse = runKubectlCommand(answers[0])
    answers.append("Kubectl run response: " + kubectlResponse)

    opsGenieAlerting = OpsGenieAlerting(
        "https://api.eu.opsgenie.com", params.opsgenie_key, "ARIS Ops Test", True, 10)
    alerts = opsGenieAlerting.getOpenAlertsByTagsAndContainingMessage(
        tags=[alert.alert.labels['cluster']], containingMessage=alert.alert.labels['alertname'])

    for a in alerts:
        opsGenieAlerting.addNoteToAlert(
            a, f"GenAI generated help: {json.dumps(answers)}", "IW test")

    alert.add_enrichment(
        [
            MarkdownBlock(json.dumps(answers))
        ]
    )
