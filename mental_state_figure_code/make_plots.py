from eval_mwoz import friction_cat, get_index, dialogue_act
import json
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import re
import numpy as np

def get_probas(arr):

    for text in arr:

        r = re.search(r'certainty\s*=\s*(\d+)', text.lower())
        try:
            p = int(r.group().split('=')[-1]) / 10
            if p > 1:
                # manually checked, almost all cases show model returns %
                p = p / 10
            if 0 <= p and p <= 1:
                yield p 
            # some wierd edge cases where model says 810% etc.
            # let these pass through
        except:
            # print(text)
            pass

# standard platt scaling
import itertools
from sklearn.linear_model import LinearRegression
from scipy.special import logit, expit

def optimize_temp_ps(y, yhat, clipval=1000):
    y = np.array(list(itertools.chain(*y)))
    yhat = np.array(list(itertools.chain(*yhat)))
    yhat = logit(yhat).reshape(-1, 1)
    yhat = np.clip(yhat, -clipval, clipval) # expit 1000 is already 1.0
    y = logit(y).reshape(-1, 1)
    y = np.clip(y, -clipval, clipval) # expit 1000 is already 1.0
    clf = LinearRegression().fit(yhat, y)
    temp = [clf.intercept_[0], clf.coef_[0][0]]
    return lambda x: expit(temp[0] + logit(x) * temp[1])

MODELS = [
    'gpt-4o-2024-05-13-multiwoz-d=0.jsonl', 
    'Llama-3-8b-chat-hf-multiwoz-d=0.jsonl',
    'Llama-3-70b-chat-hf-multiwoz-d=0.jsonl',
    'gemma-7b-it-multiwoz-d=0.jsonl', 
    'Mixtral-8x7B-Instruct-v0.1-multiwoz-d=0.jsonl', 
    'open-mixtral-8x22b-multiwoz-d=0.jsonl'
]

if __name__ == '__main__':

    # annot_file = 'outputs/Meta-Llama-3.1-70B-Instruct-Turbo-multiwoz.jsonl'
    annot_file = 'outputs/gpt-4o-2024-08-06-multiwoz.jsonl'
    with open(annot_file, 'r') as annot:
        data = [json.loads(line) for line in annot]
    
    final_cdata = None

    for model in MODELS:

        with open(model, 'r') as annot:
            cdata = [json.loads(line) for line in annot]
            for c in cdata:
                probas = list(get_probas(c['response']))
                if probas:
                    c['proba'] = sum(probas) / len(probas)
                else:
                    c['proba'] = np.nan
        
        og_cdata = cdata
        for seed in [0,1,2,3,4]:
            import copy
            cdata = cdata = copy.deepcopy(cdata)
            train = []
            import random; random.seed(seed)

            for i,c in enumerate(cdata):
                if random.random() < 0.1:
                    train.append(c)
                    del cdata[i]

            fn = optimize_temp_ps(
                [[t['p'] for t in train if not np.isnan(t['proba'])]], 
                [[t['proba'] for t in train if not np.isnan(t['proba'])]])

            if final_cdata is None: 
                final_cdata = cdata
                for x in final_cdata:
                    x['err'] = [(fn(x['proba']) - x['p']) ** 2]
            else:
                for x in final_cdata:
                    for c in cdata:
                        if x['input'] == c['input'] and not np.isnan(c['proba']):
                            x['err'].append((fn(c['proba']) - c['p']) ** 2)
        
        for x in data:
            for c in final_cdata:
                if x['input'] == c['input']:
                    x['err'] = np.nanmean(c['err'])
        
    # cdata = final_cdata
    # train = []
    # import random; random.seed(0)

    # # for i,c in enumerate(cdata):
    # #     if random.random() < 0.25:
    # #         train.append(c)
    # #         del cdata[i]
    #     # NOTE: when there was data not in use
    #     # found = False
    #     # for x in data:
    #     #     if x['input'] == c['input']:
    #     #         found = True
    #     # if not found:
    #     #     train.append(c)
    # print(len(train))

    # # fn = optimize_temp_ps([[t['p'] for t in train if not np.isnan(t['proba'])]], [[t['proba'] for t in train if not np.isnan(t['proba'])]])
    # fn = lambda x: x
    
    # for x in data:
    #     for c in cdata:
    #         if x['input'] == c['input'] and not np.isnan(c['proba']):
    #             x['err'] = (fn(c['proba']) - c['p']) ** 2
    
    # repair broken data
    with open('multiwoz.jsonl', 'r') as repair:
        repair = [json.loads(line) for line in repair]
        for x in data:
            for r in repair:
                if x['instance_id'] == r['instance_id']:
                    x['acts'] = r['acts']
    
    results = []

    for x in data:
        if 'err' not in x:
            continue
        friction = friction_cat(x['response'][0])
        aindex = get_index(x['completion'][0], x['input'])
        if aindex is None:
            continue
        act = dialogue_act(x['acts'][aindex])
        results.append({
            'friction' : friction,
            'inputs' : x['completion'][0].split('Response: ')[-1].split('\n')[0],
            'act' : act,
            'score' : x['scores'][aindex+1],
            'overall' : x['scores'][-1],
            'err' : x['err'],
            'length' : aindex,# / len(x['input'].split('\n')),
            'total' : len(x['input'].split('\n'))
        })
    
    df = pd.DataFrame(results)

    df['F/A'] = df['act'] + ' / ' + df['friction'] 
    # v = df['friction'].value_counts()
    # print(v); exit()
    # df = df[df['F/A'].isin(v.index[v.gt(5)])]

    df['err (delta)'] = df['err'] - df['err'].mean()
    df['overall (delta)'] = df['overall'] - df['overall'].mean()
    df['score (delta)'] = df['score'] - df['score'].mean()
    df['dialogue turn'] = df['total']
    df['% dialogue finished'] = df['length']

    from scipy.stats import kruskal as f_oneway
    df.dropna(inplace=True)
    df.sort_values('F/A', inplace=True)

    sns.set_theme(rc={'figure.figsize':(8,4)}, style='white', font_scale=1.5)

    # df = df[df['friction'].apply(lambda s: s in ['reinforcement', 'pause', 'none'])]
    df['friction'] = df['friction'].apply(lambda s: s if s != 'overspecification' else 'overspec')
    df['friction'] = df['friction'].apply(lambda s: s if s != 'reinforcement' else 'reinforc')


    # df['friction'] = df['friction'].apply(lambda s: 'yes' if s != 'none' else s)
    samples = [df[df['friction']==u] for u in df['friction'].unique()]
    # sns.boxplot(x='friction', y='err', data=df, palette='Blues', showfliers=False)

    sns.barplot(x='friction', y='err', data=df, palette='Blues')
    plt.title(f"Average Error in MultiWOZ by Movement | Kruskal p={f_oneway(*[s['err'] for s in samples]).pvalue:.2f}")
    plt.ylabel('Error (infering satisfaction)')
    plt.tight_layout()
    plt.savefig(f'boxplot-err'); plt.clf()

    # sns.barplot(x='friction', y='total', data=df, palette='Blues')
    # plt.title(f"Average Turns in MultiWOZ by Movement | Kruskal p={f_oneway(*[s['err'] for s in samples]).pvalue:.2f}")
    # plt.ylabel('Turns')
    # plt.tight_layout()
    # plt.savefig(f'really_new_figures/boxplot-turns'); plt.clf()

    sns.barplot(x='friction', y='total', data=df, palette='Blues')
    sns.barplot(x='friction', y='length', data=df, palette='Reds')
    plt.title(f"Average Timing in MultiWOZ by Movement")
    plt.ylabel('Turn')
    import matplotlib.patches as mpatches
    red_patch = mpatches.Patch(color='red', label='Observed Index of Movement')
    bl_patch = mpatches.Patch(color='blue', label='Total Indices (Length)')
    plt.legend(handles=[red_patch, bl_patch])
    plt.tight_layout()
    plt.savefig(f'boxplot-timing'); plt.clf()