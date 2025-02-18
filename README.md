# Applying Friction in MultiWOZ Conversations

## Install dependencies
Python 3.12 or later.
```console
❱❱❱ pip install -r requirements.txt
```

## Prepare dataset
Git clone or download [MultiWOZ 2.4](https://github.com/smartyfh/MultiWOZ2.4) repository. Run the create_data.py to prepare the dials data.
```console
❱❱❱ cd MultiWOZ2.4-main
❱❱❱ python create_data.py
```

## Generate MultiWOZ conversation with or without friction
```console
❱❱❱ python run_friction.py -out=<out_dir> -n=<num_of_conversations> -ftype=<friction_type>
```

# Evaluate
Follow the online evaluation of [AutoTOD](https://github.com/DaDaMrX/AutoTOD). Use the generated *_fm.json file for the evaluation.
