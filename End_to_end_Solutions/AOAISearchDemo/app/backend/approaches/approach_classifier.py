import openai
from backend.approaches.approach import Approach
from backend.config import DefaultConfig
from backend.contracts.chat_response import ApproachType
from common.logging.log_helper import CustomLogger
from typing import List
import re
import pandas as pd
from textwrap import dedent

class ApproachClassifier(Approach):
    def __init__(self, logger: CustomLogger):
        self.logger = logger
    
    def run(self, history: List[str], bot_config) -> ApproachType:
        # response = openai.Completion.create(
        #     prompt=history[-1]['utterance'] + ' ->',
        #     **bot_config["approach_classifier"]["openai_settings"]
        #     )
        message_list = [{
                "role": "system",
                "content": dedent(bot_config["approach_classifier_prompt"]["system_prompt"])
                 }
            ]
        
        message_list.append({"role": "user", "content": history[-1]['utterance'] + ' ->'})

        approach_response = openai.ChatCompletion.create(
            messages=message_list,
            **bot_config["approach_classifier_prompt"]["openai_settings"]
        )
        q :str = approach_response['choices'][0]['message']['content']
        #q :str = "1" # response['choices'][0]['text'].strip()
        # self.log_aoai_response_details(f'Classification Prompt:{history[-1]["utterance"]}', f'Response: {q}', response)

        if q == "1":
            return ApproachType.telemetry
            # return ApproachType.structured
        elif q == "2":
            return ApproachType.unstructured
        elif q == "3":
            return ApproachType.chit_chat
        elif q == "4":
            # Continuation: Return last question type from history if it exists
            if len(history) > 1:
                last_question_type = history[-2]['question_type']
                if last_question_type == "telemetry_query":
                    return ApproachType.telemetry
                    # return ApproachType.structured
                elif last_question_type == "unstructured_query":
                    return ApproachType.unstructured
                elif last_question_type == "chit_chat":
                    return ApproachType.chit_chat
                else:
                    raise Exception(f"Unknown question type: {last_question_type}")
            else:
                return ApproachType.unstructured
        else:
            return ApproachType.unstructured

    def log_aoai_response_details(self, prompt, result, aoai_response):
        addl_dimensions = {
            "completion_tokens": aoai_response.usage.get("completion_tokens", 0),
            "prompt_tokens": aoai_response.usage.prompt_tokens,
            "total_tokens": aoai_response.usage.total_tokens,
            "aoai_response[MS]": aoai_response.response_ms
        }
        addl_properties = self.logger.get_updated_properties(addl_dimensions)
        self.logger.info(f"prompt: {prompt}, response: {result}", extra=addl_properties)
