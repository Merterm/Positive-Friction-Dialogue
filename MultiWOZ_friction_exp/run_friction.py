from openai import OpenAI, AzureOpenAI
import json
import random
import argparse
import os
from mapping import ACTION_DOMAINS
from utils.nlp import normalize
from prompts import user_prompt, prompt_no_friction, friction_prompt_assumption, friction_prompt_overspecification, friction_prompt_probing, friction_prompt_all
from evaluator import evaluator, evaluator_rm_friction_type

#--------------------------------------

parser = argparse.ArgumentParser()
parser.add_argument('-out','--out', help='path of the output directiory', required=True)
parser.add_argument('-n','--n', help='Number of Conversations', type=int, required=False, default=100)
parser.add_argument('-ftype','--ftype', help='Friction type: pr (Probing), os (Overspecification), ar (Assumption Reveal), rf (Reinforcement), all, no', required=True, choices=['pr', 'os', 'ar', 'rf', 'all', 'no'])

args = vars(parser.parse_args())
out_dir = args['out']
n_count = args['n']
f_type = args['ftype']
if(not os.path.isdir(out_dir)):
    os.mkdir(out_dir)
out_file = os.path.join(out_dir, f"output_{f_type}.json")

print("out_file", out_file)
print("n_count", n_count)
print("friction_type", f_type)

domains_in_interest = ["taxi", "restaurant", "attraction", "hotel", "train"]

# Set Prompt class
if(f_type=="pr"):
    print(f"Selecting Probing class")
    prompt_class = friction_prompt_probing
elif(f_type=="os"):
    print(f"Selecting Overspecification class")
    prompt_class = friction_prompt_overspecification
elif(f_type=="ar"):
    print(f"Selecting Assumption Reveal class")
    prompt_class = friction_prompt_assumption
elif(f_type=="rf"):
    print(f"Selecting Reinforcement class")
    prompt_class = friction_prompt_reinforcement
elif(f_type=="all"):
    print(f"Selecting all class")
    prompt_class = friction_prompt_all
else:
    print(f"Selecting no friction")
    prompt_class = prompt_no_friction

#--------------------------------------

# Prepare Data

def get_domains_samples(data, domains_in_interest):
    domains_samples = {domain: list() for domain in domains_in_interest}
    processed_data = dict()
    for dialogue_content in data:
        for domain in dialogue_content["domains"]:
            if domain in domains_in_interest:
                domains_samples[domain].append(dialogue_content["dialogue_idx"])
                processed_data[dialogue_content["dialogue_idx"]] = dialogue_content
    return domains_samples, processed_data

# Load MultiWOZ data
with open("MultiWOZ2.4-main/data/mwz2.4/test_dials.json", "r") as f:
    data = json.load(f)
with open("MultiWOZ2.4-main/data/mwz24/data.json", "r") as f:
    old_data = json.load(f)
    
domains_samples, data = get_domains_samples(data, domains_in_interest)

total_samples = set()
total_length = 0
for domain, samples in domains_samples.items():
    total_samples = total_samples.union(set(samples))
    total_length += len(samples)

with open("shuffled_test_dials.json", "r") as f:
    total_samples = json.load(f)[:n_count]
    
print(f"Total samples: {len(total_samples)}")

#--------------------------------------

# Set System and user Model and Config

config_data = json.load(open("config.json"))
azure_endpoint = config_data["azure_endpoint"]
api_key = config_data["api_key"]
api_version = config_data["api_version"]
user_model = config_data["user_model"]
system_model = config_data["system_model"]

client_config = {
    "client": AzureOpenAI(
        azure_endpoint = azure_endpoint,
        api_key = api_key,
        api_version=api_version
    ),
    "model": system_model,
}

user_client_config = {
    "client": AzureOpenAI(
        azure_endpoint = azure_endpoint,
        api_key = api_key,
        api_version=api_version
    ),
    "model": user_model,
}

if (f_type=="no"):
    online_evaluator = evaluator(
        data,
        old_data,
        total_samples,
        prompt=prompt_class,
        user_prompt=user_prompt,
        client_config=client_config,
        user_client_config=user_client_config,
        online=True
    )
else:
    online_evaluator = evaluator_rm_friction_type(
        data,
        old_data,
        total_samples,
        prompt=prompt_class,
        user_prompt=user_prompt,
        client_config=client_config,
        user_client_config=user_client_config,
        online=True
    )

online_evaluator.evaluate()
online_evaluator.save_result(out_file)

#--------------------------------------

# Postprocess output for readability

with open(out_file, 'r') as file:
    res = json.load(file)

out_file_formatted = out_file.replace(".json", "_bt.json")
print(f"out_file_formatted: {out_file_formatted}")

c_fric = 0
c_total = 0
c_conv = 0

form_out = {}
for k in res:
    c_conv+=1
    form_out[k] = {}
    form_out[k]["goal"] = res[k]["goal_info"]["message"]
    form_out[k]["log"] = []

    sys_start = ""
    for i in range(len(res[k]["responses"])):
        c_total +=1
        dct = {}
        dct["sys"] = sys_start if (i==0) else res[k]["responses"][i-1]
        dct["usr"] = res[k]["questions"][i]
        dct["state"] = res[k]["states"][i]
        dct["response"] = res[k]["responses"][i]
        if (f_type!="no"):
            dct["friction_types"] = res[k]["friction_types"][i]
            if(len(res[k]["friction_types"][i])>0 and res[k]["friction_types"][i][0]!="No Friction"):
                c_fric+=1
        dct["answers"] = res[k]["answers"][i]
        form_out[k]["log"].append(dct)

with open(out_file_formatted, 'w', encoding='utf-8') as f:
    json.dump(form_out, f, ensure_ascii=False, indent=4)

print(f"Avg. Turn: {c_total/c_conv}")
print(f"Friction Turns: {c_fric/c_total}")

#--------------------------------------

# Postprocess output for online evaluation (AutoToD)

new_file_name =out_file.replace(".json", "_fm.json")
print(f"out_file for online eval: {new_file_name}")

processed_result = dict()
for sample_id, sample_content in res.items():
    cost = 0.0
    dialog_pred = list()
    for turn_idx, turn_response in enumerate(sample_content["responses"]):
        turn_question = sample_content["questions"][turn_idx]
        dialog_pred.append({"turn_idx": turn_idx+1, "user": turn_question, "agent": turn_response})
    goals = dict()
    for domain, domain_content in sample_content["goal_info"].items():
        if len(domain_content) != 0 and domain in ACTION_DOMAINS:
             goals[domain] = domain_content
    goal_messages = sample_content["goal_info"]["message"]
    dialog_refer = list()
    for turn_idx in range(0, len(old_data[sample_id]["log"]), 2):
        dialog_refer.append({"turn_idx": turn_idx//2+1, "user": old_data[sample_id]["log"][turn_idx]["text"], "agent": old_data[sample_id]["log"][turn_idx+1]["text"]})
    finish_status = sample_content["finish_status"] if "finish_status" in sample_content else "dialogue ends"
    processed_result[sample_id] = {"cost": cost, "dialog_pred": dialog_pred, "goals": goals, "goal_messages": goal_messages, "dialog_refer": dialog_refer, "finish_status": finish_status}

with open(new_file_name, "w") as f:
    json.dump(processed_result, f, indent=4)

#--------------------------------------