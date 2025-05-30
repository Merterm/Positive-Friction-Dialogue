import openai
import time
import yaml
from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
)  # for exponential backoff
#from bootstrapping.prompts import CHATGPT_RESPONSE_ANSWER_EXTRACTION_INSTRUCTION
from typing import Union, Dict, List, Tuple

cost_dict = {
    'chatgpt': {'input': 0.0005/1000, 'output': 0.0015/1000},
    'chatgpt-16k': {'input': 0.0015/1000, 'output': 0.002/1000},
    'gpt4': {'input': 30/1000000, 'output': 60/1000000},
    'gpt4o': {'input': 2.5/1000000, 'output': 10/1000000}
}

from openai import OpenAI


class OpenAICaller:

    def __init__(self):
        self.tokens_used = {}

        self.GPT_NAME_TO_MODEL_NAME = {
            'chatgpt': "gpt-3.5-turbo-0125",
            'chatgpt-16k': "gpt-3.5-turbo-instruct",
            'gpt4': "gpt-4",
            'gpt4o': "gpt-4o-2024-08-06",
        }
        self.VALID_CHATGPT_MODELS = ['chatgpt', 'chatgpt-16k', 'gpt4', 'gpt4o']#, 'chatgpt-16k', 'gpt4-32k', 'gpt4-1106']
        self.VALID_GPT3_MODELS = [] # ['gpt3']
        for model in self.VALID_CHATGPT_MODELS + self.VALID_GPT3_MODELS:
            self.tokens_used[model] = {
                'n_input_tokens': 0,
                'n_output_tokens': 0,
            }
        self.set_openai_keys()

    def set_openai_keys(self, openai_config_file='/home/tejas/data/openai_config_glamor.yaml'):
        '''
        Set API keys
        '''

        openai_config = yaml.safe_load(open(openai_config_file))
        #openai.organization = openai_config['org_key']
        #openai.api_key = openai_config['api_key']
        self.client = OpenAI(
            organization=openai_config['org_key'],
            api_key=openai_config['api_key']
        )


    @retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(6))
    def call_chatgpt(self, chatgpt_prompt: Union[str, List[Dict]], max_new_tokens=40, model="chatgpt", temperature=0.6, num_completions=1, **kwargs) -> Union[str, List[str]]:
        '''
        Call chatgpt
        arguments:
            chatgpt_prompt: str or list of message dictionaries
            max_new_tokens: maximum number of tokens to generate
            model: model type for chat completion
            temperature: temperature for chat completion
            num_completions: number of completions to generate
        returns:
            reply: str or list of str
            string if single completion, list of strings if multiple completions
        '''
        model_name = self.GPT_NAME_TO_MODEL_NAME[model]
        if isinstance(chatgpt_prompt, str):
            chatgpt_prompt = [{'role': 'user', 'content': chatgpt_prompt}]
        response = self.client.chat.completions.create(
            model=model_name, 
            messages=chatgpt_prompt, 
            temperature=temperature, 
            max_tokens=max_new_tokens,
            n=num_completions,
            **kwargs
        )
        if num_completions == 1:
            reply = response.choices[0].message.content
        else:
            reply = [x.message.content for x in response.choices]
        #print(response['usage'])
        self.tokens_used[model]['n_input_tokens'] += response.usage.prompt_tokens
        self.tokens_used[model]['n_output_tokens'] += response.usage.completion_tokens
        #print("Prompt tokens used: {}".format(response['usage']['prompt_tokens']))
        #print(f"Total tokens used: {response['usage']['prompt_tokens'] + response['usage']['completion_tokens']}")
        return reply

    @retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(6))
    def call_gpt3(self, gpt3_prompt: str, max_new_tokens=40, model="gpt3", temperature=0.6, num_completions=1) -> str:
        '''
        Call gpt3
        arguments:
            gpt3_prompt: str
            max_new_tokens: maximum number of tokens to generate
            model: model type for string completion
            temperature: temperature for string completion
            num_completions: number of completions to generate
        returns:
            reply: str
        '''
        model_name = self.GPT_NAME_TO_MODEL_NAME[model]
        response = openai.Completion.create(
            model=model_name, 
            prompt=gpt3_prompt, 
            max_tokens=max_new_tokens, 
            temperature=temperature,  # temperature=0.6
            n=num_completions,
        ) 
        reply = response['choices'][0]['text']
        self.tokens_used[model]['n_input_tokens'] += response['usage']['prompt_tokens']
        self.tokens_used[model]['n_output_tokens'] += response['usage']['completion_tokens']
        return reply

    def __call__(self, prompt: Union[str, List[Dict]], max_new_tokens=40, model="gpt3", temperature=0.6, num_completions=1, **kwargs):
        '''
        Call gpt3 or chatgpt
        arguments:
            prompt: str or list of message dictionaries
            max_new_tokens: maximum number of tokens to generate
            model: model type for completion
            temperature: temperature for completion
            num_completions: number of completions to generate
        '''
        if model in self.VALID_GPT3_MODELS:
            assert isinstance(prompt, str)
            return self.call_gpt3(prompt, max_new_tokens=max_new_tokens, model=model, temperature=temperature, num_completions=num_completions)
        elif model in self.VALID_CHATGPT_MODELS:
            return self.call_chatgpt(prompt, max_new_tokens=max_new_tokens, model=model, temperature=temperature, num_completions=num_completions, **kwargs)
            #while True:
            #    try:
            #    except openai.RateLimitError:
            #        print("Rate limit error. Retrying...")
            #        time.sleep(10)
            #    except Exception as e:
            #        print("Unknown error. Retrying...")
            #        print(str(e))
            #        time.sleep(10)
            #        import pdb; pdb.set_trace()
        else:
            raise ValueError("Invalid model name: {}".format(model))

    def compute_cost(self, model="all"):
        '''
        Compute total cost of API calls
        '''
        cost = 0
        if model == "all":
            models_to_consider = self.VALID_CHATGPT_MODELS + self.VALID_GPT3_MODELS
        else:
            models_to_consider = [model]
        for model in models_to_consider:
            cost += cost_dict[model]['input'] * self.tokens_used[model]['n_input_tokens']
            cost += cost_dict[model]['output'] * self.tokens_used[model]['n_output_tokens']
        return cost

    def reset_tokens_used(self, model="all"):
        '''
        Reset number of tokens used for specific model type (all by default)
        '''
        if model == "all":
            models_to_consider = self.VALID_CHATGPT_MODELS + self.VALID_GPT3_MODELS
        else:
            models_to_consider = [model]
        for model in models_to_consider:
            self.tokens_used[model]['n_input_tokens'] = 0
            self.tokens_used[model]['n_output_tokens'] = 0


openai_caller = OpenAICaller()