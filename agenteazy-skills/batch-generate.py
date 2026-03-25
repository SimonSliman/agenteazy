#!/usr/bin/env python3
"""Generate all skill folders from batch-manifest.json and deploy them."""
import json
import os
import subprocess
import sys

MANIFEST = os.path.join(os.path.dirname(__file__), "batch-manifest.json")
SKILLS_DIR = os.path.dirname(__file__)

with open(MANIFEST) as f:
    skills = json.load(f)

generated = []
for skill in skills:
    name = skill["name"]
    skill_dir = os.path.join(SKILLS_DIR, name)
    os.makedirs(skill_dir, exist_ok=True)

    # main.py
    main = f"""{skill['import']}


def {skill['function']}({skill['args']}):
    try:
        {skill['body']}
    except Exception as e:
        return {{"error": str(e)}}
"""
    with open(os.path.join(skill_dir, "main.py"), "w") as f:
        f.write(main)

    # agent.json
    agent = {"name": name, "entry": skill["function"], "verbs": ["DO", "ASK"]}
    with open(os.path.join(skill_dir, "agent.json"), "w") as f:
        json.dump(agent, f, indent=2)

    # requirements.txt
    reqs = skill.get("requirements", "").strip()
    reqs_lines = reqs.split("\n") if reqs else []
    reqs_lines += ["fastapi", "uvicorn"]
    with open(os.path.join(skill_dir, "requirements.txt"), "w") as f:
        f.write("\n".join(reqs_lines) + "\n")

    generated.append(name)
    print(f"  Generated: {name}/")

print(f"\n{len(generated)} skills generated. Now run:")
print(f"  git add -A && git commit -m 'Batch generate {len(generated)} skills' && git push")
print(f"\nThen deploy each:")
for skill in skills:
    name = skill["name"]
    func = skill["function"]
    price = skill["price"]
    print(f"  rm -rf /tmp/agenteazy && agenteazy deploy SimonSliman/agenteazy --entry 'agenteazy-skills/{name}/main.py:{func}' --name {name} --price {price}")
