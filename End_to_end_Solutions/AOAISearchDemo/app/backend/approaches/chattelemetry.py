import json
import openai
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
from azure.kusto.data.exceptions import KustoServiceError
from azure.kusto.data.helpers import dataframe_from_result_table
import re
import pandas as pd
from backend.approaches.approach import Approach
from backend.config import DefaultConfig
from backend.contracts.chat_response import Answer, ApproachType, ChatResponse
from backend.contracts.error import OutOfScopeException, UnauthorizedDBAccessException
from backend.utilities.openai_utils import generate_history_messages
from backend.utilities.prompt_composer_utils import trim_history, compute_tokens
from common.logging.log_helper import CustomLogger
from textwrap import dedent

# Telemetry information retrieval, using Azure kql, Azure IoTHub and Azure OpenAI APIs directly. 
class ChatTelemetryApproach(Approach):
    def __init__(self, cluster_name: str, database_name: str, kusto_authority_id:str, kusto_application_id:str, kusto_application_key:str, kusto_tenant_id:str, logger: CustomLogger):
        self.cluster_name = cluster_name
        self.database_name = database_name
        self.kusto_uri = "https://" + cluster_name + ".eastus.kusto.windows.net"
        self.kusto_authority_id = kusto_authority_id  # Required for Azure AD authentication
        self.kcsb = KustoConnectionStringBuilder.with_aad_application_key_authentication(self.kusto_uri, kusto_application_id, kusto_application_key, kusto_authority_id)
        self.logger = logger


    def run(self, history, bot_config, overrides: dict, context: dict) -> any:        
        unauthorized_error_messages = ["I am not authorized to make changes to the data"]

        # STEP 1: Generate an kql query using the chat history
        message_list = [{
                "role": "system",
                "content": dedent(bot_config["telemetry_query_nl_to_kql"]["system_prompt"])
                 }
            ]
        
        if bot_config["telemetry_query_nl_to_kql"]["history"]["include"]:
            chat_history = generate_history_messages(history[:-1], bot_config["telemetry_query_nl_to_kql"]["history"])
            chat_history = trim_history(chat_history, 
                                        bot_config["telemetry_query_nl_to_kql"]["model_params"]["total_max_tokens"] - compute_tokens(bot_config["telemetry_query_nl_to_kql"]["system_prompt"]) - bot_config["telemetry_query_nl_to_kql"]["openai_settings"]["max_tokens"],
                                        bot_config["telemetry_query_nl_to_kql"]["model_params"]["model_name"])
            message_list.extend(chat_history)
            
        contextString = ""
        if context:
            json.dumps(context)
            contextString += 'Context: '+json.dumps(context)
        message_list.append({"role": "user", "content": contextString  + ' | User question: ' + history[-1]['utterance'] + " kql Code: "})

        nl_to_kql_response = openai.ChatCompletion.create(
            messages=message_list,
            **bot_config["telemetry_query_nl_to_kql"]["openai_settings"]
        )

        generated_kql_query = nl_to_kql_response['choices'][0]['message']['content']
        self.log_aoai_response_details(json.dumps(message_list), generated_kql_query, nl_to_kql_response)
        answer = Answer()

        # STEP 2: Run generated kql query against the database
        kql_result = None

        if "ERROR:" in generated_kql_query:
            if any(message in generated_kql_query for message in unauthorized_error_messages):
                raise UnauthorizedDBAccessException("Error: I am not allowed to make changes to the data.")
            m = re.search(r"ERROR:(.*?)\.", generated_kql_query)
            if m:
                raise OutOfScopeException(message=m.group(1), suggested_classification=ApproachType.unstructured)

        answer.query = generated_kql_query
        try:
            kql_result = self.execute_kusto_query(self.kcsb, self.database_name, generated_kql_query)
        except pd.errors.DatabaseError as e:
            raise OutOfScopeException(message=str(e), suggested_classification=ApproachType.unstructured)
        except Exception as e:
            raise Exception(f"Unknown error when querying kql database: {str(e)}")
               
        # STEP 3: Format the kql query and kql result into a natural language response
        if kql_result is not None:
            answer.query_result = kql_result
            message_list = [{
                    "role": "system",
                    "content": dedent(bot_config["telemetry_final_answer_generation"]["system_prompt"])
                    }
                ]

            if bot_config["telemetry_final_answer_generation"]["history"]["include"]:
                message_list.extend(generate_history_messages(history[:-1], bot_config["telemetry_final_answer_generation"]["history"]))
            
            message_list.append({"role": "user", "content": "Question: " + str(history[-1]['utterance']) + "\nAnswer:\n" + str(kql_result)})

            kql_result_to_nl_response = openai.ChatCompletion.create(
                messages=message_list,
                **bot_config["telemetry_final_answer_generation"]["openai_settings"]
            )

            formatted_kql_result = kql_result_to_nl_response['choices'][0]['message']['content']

            self.log_aoai_response_details(json.dumps(message_list), json.dumps(formatted_kql_result), kql_result_to_nl_response)

            answer.formatted_answer = formatted_kql_result

        return ChatResponse(classification=ApproachType.telemetry, answer=answer)


    def execute_kusto_query(self, kcsb, database, query):
        try:
            client = KustoClient(kcsb)
            response = client.execute(database, query)
            res = dataframe_from_result_table(response.primary_results[0])
            return res.to_dict(orient='records')
        except KustoServiceError as ex:
            print("Error executing Kusto query:", ex)
            return None

    def log_aoai_response_details(self, prompt, result, aoai_response):
        addl_dimensions = {
            "completion_tokens": aoai_response.usage.completion_tokens,
            "prompt_tokens": aoai_response.usage.prompt_tokens,
            "total_tokens": aoai_response.usage.total_tokens,
            "aoai_response[MS]": aoai_response.response_ms
        }
        addl_properties = self.logger.get_updated_properties(addl_dimensions)
        self.logger.info(f"prompt: {prompt}, response: {result}", extra=addl_properties)