import json
import pandas as pd
from statsmodels.formula.api import ols

def friction_cat(response):

    kwords = ['reveal', 'pause', 'reinforcement', 'overspecification', 'probing']
    prediction = -1
    for i, k in enumerate(kwords):
        if k in response.split('=')[-1].lower():
            prediction = i
    kwords += ['none']
    return kwords[prediction]

def get_index(comp, turns):
    turn = comp.split('Response: ')[-1].split('\n')[0]
    turns = turns.split('\n')[1:]
    j = None
    for i, t in enumerate(turns):
        if t == turn:
            j = i
    return j

def dialogue_act(response):
    kwords = ['Book', 'Select', 'Request', 'general-welcome', 'general-reqmore', 'Inform', 'NoOffer', 'general-thank', 'OfferBook', 'OfferBooked', 'general-greet', 'Recommend', 'general-bye', 'NoBook']
    prediction = -1
    for i, k in enumerate(kwords):
        if k in response:
            prediction = i
    kwords += ['none']
    return kwords[prediction]
    
if __name__ == '__main__':

    with open('outputs/Meta-Llama-3.1-70B-Instruct-Turbo-multiwoz.jsonl', 'r') as annot:
        data = [json.loads(line) for line in annot]
    
    # repair broken data
    with open('multiwoz.jsonl', 'r') as repair:
        repair = [json.loads(line) for line in repair]
        for x in data:
            for r in repair:
                if x['instance_id'] == r['instance_id']:
                    x['acts'] = r['acts']
    
    results = []

    for x in data:
        friction = friction_cat(x['response'][0])
        aindex = get_index(x['completion'][0], x['input'])
        if aindex is None:
            continue
        act = dialogue_act(x['acts'][aindex])
        results.append({
            'friction' : friction,
            'act' : act,
            'score' : x['scores'][aindex+1],
            'overall' : x['scores'][-1],
            'length' : aindex / len(x['input'].split('\n')),
            'total' : len(x['input'].split('\n'))
        })
    
    df = pd.DataFrame(results)
    # model = ols('overall ~ friction + act + length + length * friction + length * act', data=df).fit()
    model = ols('overall ~ friction + act + total + total * friction + total * act', data=df).fit()
    # model = ols('overall ~ act + length + length * act', data=df).fit()
    # model = ols('overall ~ friction + act', data=df).fit()
    # model = ols('overall ~ friction', data=df).fit()
    # model = ols('length ~ friction + act', data=df).fit()
    print(model.summary())
    print(f'resid: {sum(model.resid) / len(model.resid):.6f}')