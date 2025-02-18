"""
Change the client attributes and model name if needed.
"""

import json
import re
from datetime import datetime
from getpass import getpass

import backoff
import gradio as gr
import openai

# from easyllm.clients import huggingface
from openai import AzureOpenAI, OpenAI
from pytz import timezone
from together import Together

from mapping import ACTION_DOMAINS, DOMAIN_FINITE_KEYS


class ChatBot:
    def __init__(self, system="", client_config=dict(), known_actions=dict(), max_internal_turns=10):
        self.system = system
        self.client_config = client_config
        self._reset_messages()
        if self.client_config:
            self.client = client_config.get("client", None)
            self.model = client_config.get("model", None)
            self.local_model = client_config.get("local_model", None)
        # if (self.client is None or self.model is None) and (self.local_model is None):
        #     print("Using the default client config!")
        #     print("endpoint:\thttps://uiuc-convai-sweden.openai.azure.com/")
        #     print("api_version:\t2024-02-15-preview")
        #     print("model:\tUIUC-ConvAI-Sweden-GPT4")
        #     self.client = AzureOpenAI(
        #         azure_endpoint = "https://uiuc-convai-sweden.openai.azure.com/",
        #         api_key = getpass("🔑 Enter your OpenAI API key: "),
        #         api_version="2024-02-15-preview"
        #     )
        #     self.model = "UIUC-ConvAI-Sweden-GPT4"
        self.known_actions = known_actions

        self.action_re = re.compile("API Name: (.*?)API Input: (.*?)API Result:", flags=re.DOTALL)
        self.response_re = re.compile("Response: (.*)", flags=re.DOTALL)
        self.action_last_line = "API Result:"    # Last line of action will be guarranteed to be this value.
        self.max_internal_turns = max_internal_turns

    def __call__(self, message):
        self.messages.append({"role": "user", "content": message})
        result = self._execute()
        result = "" if result is None else result
        self.messages.append({"role": "assistant", "content": result})
        return result

    @backoff.on_exception(backoff.expo, openai.RateLimitError)
    def _execute(self):
        if self.local_model is None:
            if isinstance(self.client, OpenAI) or isinstance(self.client, AzureOpenAI) or isinstance(self.client, Together):
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=self.messages,
                    temperature=0,
                )
                with open("API_calls_record.txt", "a") as f:
                    try:
                        f.write(f"""Time: {datetime.now(timezone("America/Chicago"))}, \tmodel: {self.model}, \tprompt_tokens: {response.usage.prompt_tokens}, \tcompletion_tokens: {response.usage.completion_tokens}, \ttotal_tokens: {response.usage.total_tokens}\n""")
                    except:
                        f.write(f"""Time: {datetime.now(timezone("America/Chicago"))}, \tmodel: {self.model}\n""")
                return response.choices[0].message.content
            # elif isinstance(self.client, huggingface):
            #     response = self.client.ChatCompletions.create(
            #         model=self.model,
            #         messages=self.messages
            #     )
            #     with open("API_calls_record.txt", "a") as f:
            #         try:
            #             f.write(f"""Time: {datetime.now(timezone("America/Chicago"))}, \tmodel: {self.model}, \tprompt_tokens: {response["usage"]["prompt_tokens"]}, \tcompletion_tokens: {response["usage"]["completion_tokens"]}, \ttotal_tokens: {response["usage"]["total_tokens"]}\n""")
            #         except:
            #             f.write(f"""Time: {datetime.now(timezone("America/Chicago"))}, \tmodel: {self.model}\n""")
            #     return response["choices"][0]["message"]["content"]
        else:
            response = self.local_model.create_chat_completion(self.messages)

    def start_session(self, debug=False):
        while True:
            question = input("[User]\n")
            if question == "Exit.":
                break
            answer = self._session(question, debug=debug)
            print(f"[Assistant]\n{answer}")

    def _session(self, message, debug=False):
        self._clean_messages()
        if debug:
            print(json.dumps(self.messages))
            
        result = self.__call__(message).strip()
        action_regex_result = self.action_re.search(result)
        turn_count = 0
        while action_regex_result and turn_count < self.max_internal_turns:
            action, action_input = action_regex_result.groups()
            action, action_input = action.strip(), action_input.strip()
            # if action not in self.known_actions:
            #     raise Exception(f"Unknown action: {action}: {action_input}")
            api_result = self.known_actions[action](action_input).strip()
            result += " " + api_result + "\n"
            new_result = self.__call__(api_result).strip()
            result += new_result
            action_regex_result = self.action_re.search(new_result)
            turn_count += 1
        return result

    def _clean_messages(self):
        for message in self.messages:
            content_lines = message["content"].split("\n")
            content_lines = [line for line in content_lines if line]
            if message["role"] == "assistant" and self.action_last_line in message["content"].split("\n")[-1]:
                content_lines[-1] = self.action_last_line
                message["content"] = "\n".join(content_lines)
    
    def start_gradio_session(self):
        gr.ChatInterface(
            self._gradio_session,
            additional_inputs=[
                gr.Checkbox(label="Debug"),
            ]
        ).launch(share=True)

    def _gradio_session(self, message, history, debug=False):
        self._reset_messages(history)
        self._clean_messages()
        if debug:
            print(json.dumps(self.messages))
            
        result = self.__call__(message).strip()
        yield result + "[To Be Continued]"
        action_regex_result = self.action_re.search(result)
        turn_count = 0
        while action_regex_result and turn_count < self.max_internal_turns:
            action, action_input = action_regex_result.groups()
            action, action_input = action.strip(), action_input.strip()
            # if action not in self.known_actions:
            #     raise Exception(f"Unknown action: {action}: {action_input}")
            api_result = self.known_actions[action](action_input).strip()
            result += " " + api_result + "\n"
            yield result + "[To Be Continued]"
            new_result = self.__call__(api_result).strip()
            result += new_result
            yield result + "[To Be Continued]"
            action_regex_result = self.action_re.search(new_result)
            turn_count += 1
        yield result

    def _reset_messages(self, history=[]):
        self.messages = []
        if self.system:
            self.messages.append({"role": "system", "content": self.system})
        for history_turn in history:
            user_utter, assistant_database_utter = history_turn[0], history_turn[1]
            self.messages.append({"role": "user", "content": user_utter})
            split_re = re.compile(r"API Result: (.*?)Thought: ", flags=re.DOTALL)
            assistant_database_split = split_re.split(assistant_database_utter)
            for i, one_assistant_database_utter in enumerate(assistant_database_split):
                if i % 2 == 0:
                    # This utterance belongs to assistant
                    if i != 0:
                        one_assistant_database_utter = "Thought: " + one_assistant_database_utter
                    if i != len(assistant_database_split) - 1:
                        one_assistant_database_utter = one_assistant_database_utter + "API Result: "
                    self.messages.append({"role": "assistant", "content": one_assistant_database_utter})
                else:
                    # This utterance belongs to database
                    self.messages.append({"role": "user", "content": one_assistant_database_utter})

class ChatBot_for_eval(ChatBot):
    def __init__(self, system="", client_config=dict(), known_actions=dict(), max_internal_turns=5):
        super().__init__(system=system, client_config=client_config, known_actions=known_actions, max_internal_turns=max_internal_turns)
    
    def eval_session(self, message, debug=False):
        self._clean_messages()
        if debug:
            print(f"message:\n{message}")
            
        result = self.__call__(message).strip()
        if debug:
            print(f"result:\n{result}")
        action_inputs = list()
        action_outputs = list()
        action_regex_result = self.action_re.search(result)
        turn_count = 0
        json_re = re.compile("({.*})", flags=re.DOTALL)
        while action_regex_result and turn_count < self.max_internal_turns:
            action, action_input = action_regex_result.groups()
            action, action_input = action.strip(), action_input.strip()
            # if action not in self.known_actions:
            #     raise Exception(f"Unknown action: {action}: {action_input}")
            try:
                json_str = json_re.search(action_input).groups()[0]
                query = json.loads(json_str)
                query["action"] = action
            except:
                query = {"action": "unknown"}
            action_inputs.append(query)
            api_result = self.known_actions[action](action_input).strip()
            action_outputs.append(json.loads(api_result))
            if debug:
                print(f"api result:\n{api_result}")
            result += " " + api_result + "\n"
            new_result = self.__call__(api_result).strip()
            if debug:
                print(f"result:\n{new_result}")
            result += new_result
            action_regex_result = self.action_re.search(new_result)
            turn_count += 1
        response_regex_result = self.response_re.search(result)
        if response_regex_result:
            response = response_regex_result.groups()[0]
        else:
            response = None
        return result, action_inputs, action_outputs, response
    
# class ChatBot_for_eval_with_frction(ChatBot_for_eval):
#     def __init__(self, system="", client_config=dict(), known_actions=dict(), max_internal_turns=5):
#         super().__init__(system, client_config, known_actions, max_internal_turns)

#     def insert_friction(self, questions, answers, old_actions=None):
#         if isinstance(questions, list):
#             assert isinstance(answers, list)
#             ract_question = f"""Thought: I have some API input values not very sure of.\nResponse: {questions[0]}"""
#             self.messages[-1] = {"role": "assistant", "content": ract_question}
#             for i in range(len(answers)-1):
#                 self.messages.append({"role": "user", "content": answers[i]})
#                 self.messages.append({"role": "assistant", "content": questions[i+1]})
#             if old_actions:
#                 return self.eval_session_dst(answers[-1], old_actions)
#             else:
#                 return self.eval_session(answers[-1])
#         else:
#             assert isinstance(answers, str)
#             ract_question = f"""Thought: I have some API input values not very sure of.\nResponse: {questions}"""
#             self.messages[-1] = {"role": "assistant", "content": ract_question}
#             if old_actions:
#                 return self.eval_session_dst(answers, old_actions)
#             else:
#                 return self.eval_session(answers)
            
#     def eval_session_dst(self, message, old_actions):
#         self._clean_messages()
            
#         result = ""
#         self.messages.append({"role": "user", "content": message})
#         new_result = f"""Thought: I need to call an API.\nAPI Name: {old_actions[0]["action"]}\nAPI Input: {json.dumps(old_actions[0]["inputs"])}\nAPI Result: """
#         self.messages.append({"role": "assistant", "content": new_result})
#         action_inputs = list()
#         action_outputs = list()
#         action_regex_result = self.action_re.search(new_result)
#         turn_count = 0
#         json_re = re.compile("({.*})", flags=re.DOTALL)
#         while action_regex_result and turn_count < self.max_internal_turns:
#             result += new_result
#             action, action_input = action_regex_result.groups()
#             action, action_input = action.strip(), action_input.strip()
#             try:
#                 json_str = json_re.search(action_input).groups()[0]
#                 query = json.loads(json_str)
#                 query["action"] = action
#             except:
#                 query = {"action": "unknown"}
#             action_inputs.append(query)
#             api_result = self.known_actions[action](action_input).strip()
#             action_outputs.append(json.loads(api_result))
#             result += " " + api_result + "\n"
#             if turn_count + 1 >= len(old_actions):
#                 new_result = self.__call__(api_result).strip()
#             else:
#                 self.messages.append({"role": "user", "content": api_result})
#                 new_result = f"""Thought: I need to call an API.\nAPI Name: {old_actions[turn_count + 1]["action"]}\nAPI Input: {json.dumps(old_actions[turn_count + 1]["inputs"])}\nAPI Result: """
#                 self.messages.append({"role": "assistant", "content": new_result})
#             action_regex_result = self.action_re.search(new_result)
#             turn_count += 1
#         result += new_result
#         response_regex_result = self.response_re.search(result)
#         if response_regex_result:
#             response = response_regex_result.groups()[0]
#         else:
#             response = None
#         return result, action_inputs, action_outputs, response
    
#     def revisit_with_fp(self, false_positives):
#         last_user_idx = 1
#         for i in range(len(self.messages)-2, -1, -1):
#             if self.messages[i]["role"] == "assistant" and self.response_re.search(self.messages[i]["content"]):
#                 last_user_idx = i + 1
#                 break
#         assert self.messages[last_user_idx]["role"] == "user"
#         user_utterance = self.messages[last_user_idx]["content"]
#         self.messages = self.messages[:last_user_idx]
#         return self.eval_session_fp(user_utterance, false_positives)
    
#     def eval_session_fp(self, message, false_positives):
#         self._clean_messages()
            
#         result = ""
#         new_result = self.__call__(message).strip()
#         action_inputs = list()
#         action_outputs = list()
#         action_regex_result = self.action_re.search(new_result)
#         turn_count = 0
#         json_re = re.compile("({.*})", flags=re.DOTALL)
#         while action_regex_result and turn_count < self.max_internal_turns:
#             action, action_input = action_regex_result.groups()
#             action, action_input = action.strip(), action_input.strip()
#             try:
#                 json_str = json_re.search(action_input).groups()[0]
#                 query = json.loads(json_str)
#                 new_query = self._remove_fp(action, query, false_positives)
#                 new_result = new_result.replace(action_input, json.dumps(new_query))
#                 result += new_result
#                 action_input = json.dumps(new_query)
#                 query = new_query
#                 query["action"] = action
#             except:
#                 result += new_result
#                 query = {"action": "unknown"}
#             action_inputs.append(query)
#             api_result = self.known_actions[action](action_input).strip()
#             action_outputs.append(json.loads(api_result))
#             result += " " + api_result + "\n"
#             new_result = self.__call__(api_result).strip()
#             action_regex_result = self.action_re.search(new_result)
#             turn_count += 1
#         result += new_result
#         response_regex_result = self.response_re.search(result)
#         if response_regex_result:
#             response = response_regex_result.groups()[0]
#         else:
#             response = None
#         return result, action_inputs, action_outputs, response
    
#     def _remove_fp(self, action, action_input, fp):
#         current_domain = None
#         for domain in ACTION_DOMAINS:
#             if domain in action:
#                 current_domain = domain
#         ret_action_input = dict()
#         if current_domain:
#             for slot, value in action_input.items():
#                 if current_domain not in fp or slot not in fp[current_domain] or value != fp[current_domain][slot]:
#                     ret_action_input[slot] = value
#             return ret_action_input
#         else:
#             return action_input
    
# class ChatBot_for_eval_without_dst(ChatBot):
#     def __init__(self, system="", client_config=dict(), known_actions=dict(), max_internal_turns=5):
#         super().__init__(system=system, client_config=client_config, known_actions=known_actions, max_internal_turns=max_internal_turns)

#     def eval_session(self, message, debug=False, dst=None):
#         self._clean_messages()
#         if debug:
#             print(f"message:\n{message}")
            
#         result = self.__call__(message).strip()
#         new_result = ""
#         if debug:
#             print(f"result:\n{result}")
#         action_inputs = list()
#         action_outputs = list()
#         action_regex_result = self.action_re.search(result)
#         turn_count = 0
#         json_re = re.compile("({.*})", flags=re.DOTALL)
#         while action_regex_result and turn_count < self.max_internal_turns:
#             action, action_input_original = action_regex_result.groups()
#             current_domain = ""
#             for domain in ACTION_DOMAINS:
#                 if domain in action:
#                     current_domain = domain
#             if dst is not None:
#                 query = dst.get(current_domain, dict())
#                 action_input = json.dumps(query)
#                 # print("action_input", action_input)
#                 # print("dst", dst)
#                 if len(new_result) == 0:
#                     result = result.replace(action_input_original, action_input+"\n")
#                 else:
#                     new_result = new_result.replace(action_input_original, action_input+"\n")
#                 self.messages[-1]["content"] = self.messages[-1]["content"].replace(action_input_original, action_input+"\n")
#             else:
#                 action_input = action_input_original
#             result += new_result
            
#             action, action_input = action.strip(), action_input.strip()
#             # if action not in self.known_actions:
#             #     raise Exception(f"Unknown action: {action}: {action_input}")
#             json_str = json_re.search(action_input).groups()[0]
#             query = json.loads(json_str)
#             query["action"] = action
#             action_inputs.append(query)
#             api_result = self.known_actions[action](action_input).strip()
#             action_outputs.append(json.loads(api_result))
#             if debug:
#                 print(f"api result:\n{api_result}")
#             result += " " + api_result + "\n"
#             new_result = self.__call__(api_result).strip()
#             if debug:
#                 print(f"result:\n{new_result}")
#             action_regex_result = self.action_re.search(new_result)
#             turn_count += 1
#         result += new_result
#         response_regex_result = self.response_re.search(result)
#         if response_regex_result:
#             response = response_regex_result.groups()[0]
#         else:
#             response = None
#         return result, action_inputs, action_outputs, response

class ChatBot_for_usersim(ChatBot):
    def __init__(self, system="", client_config=dict(), known_actions=dict(), max_internal_turns=10):
        super().__init__(system=system, client_config=client_config, known_actions=known_actions, max_internal_turns=max_internal_turns)

    def sim_session(self, message, debug=False):
        if debug:
            print(json.dumps(self.messages))
        result = self.__call__(message).strip()
        return result
    
class ChatBot_for_verification(ChatBot):
    def __init__(self, system="", client_config=dict(), known_actions=dict(), max_internal_turns=10):
        super().__init__(system=system, client_config=client_config, known_actions=known_actions, max_internal_turns=max_internal_turns)

    def veri_session(self, message, debug=False):
        if debug:
            print(json.dumps(self.messages))
        result = self.__call__(message).strip()
        return result
    
class ChatBot_for_friction(ChatBot):
    def __init__(self, system="", client_config=dict(), known_actions=dict(), max_internal_turns=10):
        super().__init__(system=system, client_config=client_config, known_actions=known_actions, max_internal_turns=max_internal_turns)

    def friction_session(self, message, debug=False):
        if debug:
            print(json.dumps(self.messages))
        result = self.__call__(message).strip()
        return result