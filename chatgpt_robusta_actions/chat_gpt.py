import logging
import time

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


@action
def show_chat_gpt_search(event: ExecutionBaseEvent, params: ChatGPTParams):
    """
    Add a finding with ChatGPT top results for the specified search term.
    This action can be used together with the stack_overflow_enricher.
    """
    openai.api_type = "azure"
    openai.api_base = params.azure_openai_api_base
    openai.api_version = "2023-05-15"
    openai.api_key = params.azure_openai_token
    deployment_id = params.azure_openai_deployment_id

    logging.info(f"ChatGPT search term: {params.search_term}")

    answers = []
    try:
        if params.search_term in lru_cache:
            answers = lru_cache[params.search_term]
        else:
            start_time = time.time()
            input = [
                {"role": "system", "content": "You are a helpful assistant. Provide kubectl commands only, no explanations!"},
                {"role": "user",
                 "content": f"Can you analyze the alert and make a Kubernetes command to solve it? Provide only the command, no explanation!\n{params.search_term}"}
            ]

            logging.info(f"ChatGPT input: {input}")
            res: OpenAIObject = openai.ChatCompletion.create(
                deployment_id=deployment_id,
                model=params.model,
                messages=input,
                max_tokens=1000,
                temperature=0
            )
            if res:
                logging.info(f"ChatGPT response: {res}")
                total_tokens = res.usage['total_tokens']
                time_taken = time.time() - start_time
                response_content = res.choices[0].message.content
                # Store only the main response in the cache
                lru_cache[params.search_term] = [response_content]
                answers.append(response_content)

            answers.append(f"\n\n ---")
            answers.append(
                f"\n\n | Time taken: {time_taken:.2f} seconds | Total tokens used: {total_tokens} |")

    except Exception as e:
        answers.append(f"Error calling ChatCompletion.create: {e}")
        raise

    finding = Finding(
        title=f"ChatGPT ({params.model}) Results",
        source=FindingSource.PROMETHEUS,
        aggregation_key="ChatGPT Wisdom",
    )

    if answers:
        finding.add_enrichment([MarkdownBlock('\n'.join(answers))])
    else:
        finding.add_enrichment(
            [
                MarkdownBlock(
                    f'Sorry, ChatGPT doesn\'t know anything about "{params.search_term}"'
                )
            ]
        )
    event.add_finding(finding)


@action
def chat_gpt_enricher(alert: PrometheusKubernetesAlert, params: ChatGPTTokenParams):
    """
    Add a button to the alert - clicking it will ask chat gpt to help find a solution.
    """
    alert_name = alert.alert.labels.get("alertname", "")
    if not alert_name:
        return
    
    alert.add_enrichment(
        [
            CallbackBlock(
                {
                    f'Ask ChatGPT: {alert_name}': CallbackChoice(
                        action=show_chat_gpt_search,
                        action_params=ChatGPTParams(
                            search_term=f"{alert_name}",
                            azure_openai_token=params.azure_openai_token,
                            azure_openai_api_base=params.azure_openai_api_base,
                            azure_openai_deployment_id=params.azure_openai_deployment_id
                        ),
                    )
                },
            )
        ]
    )
