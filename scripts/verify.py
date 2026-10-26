"""No-hardware verification, isolating Qt and camera mocks per process."""
from pathlib import Path
import os
import subprocess
import sys
root=Path(__file__).resolve().parents[1]
commands=[['-m','unittest','discover','-s','tests','-p','test_camera.py','-v']]
commands += [[str(p)] for p in sorted((root/'tests').glob('test_*.py')) if p.name!='test_camera.py']
for command in commands:
    environment = {**os.environ, 'PYTHONPATH': str(root)}
    subprocess.run([sys.executable,*command],cwd=root,env=environment,check=True,timeout=90)
print('All non-hardware checks passed.')
