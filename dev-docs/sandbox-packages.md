# Sandbox Package Inventory

This app is designed to run inside restricted Python environments — typically code-execution sandboxes attached to LLM agents (open-source or otherwise), but the rules apply to any Python 3.10+ install that lacks network access or the ability to `pip install`.

The list below is a real snapshot of one such environment's pre-installed packages. Treat it as a concrete example of what we can realistically count on being available, not a promise about any specific host. The app must work when this exact set is present, and it should not silently fail when a subset is present.

## Ground rules

- **Runtime (`scripts/`)** imports only from the Python standard library. No exceptions. This rule exists precisely so we never depend on whatever the host happens to ship.
- **Tests + dev tooling** (`tests/`, `tools/`, `requirements-dev.txt`, `pyproject.toml`) live outside the deployable tree. `make package` strips them out before zipping. That means dev-time `requirements-dev.txt` is free to pin whatever's convenient — `pytest`, `coverage`, `ruff`, `mypy`, and so on.
- **The deployed app** never ships dev tooling or tests. What lands in the target environment is the `scripts/` tree plus an empty `db/datasource.db` (see `tools/package.py`).

Bottom line: at runtime, stay stdlib. Everything else is free on the dev side.

## Snapshot — example host package set

Last verified: 2026-04-27 from one hosted sandbox. Version bumps or differences in another environment don't affect this app (the runtime needs none of these), but refresh the snapshot if you rely on a specific version for tests.

```
DendroPy==5.0.8
FXrays==1.3.6
MIDIUtil==1.2.1
PyGObject==3.48.2
PyJWT==2.7.0
PyYAML==6.0.1
aiofiles==25.1.0
annotated-types==0.7.0
anyio==4.13.0
astropy-iers-data==0.2026.4.27.1.3.2
astropy==7.2.0
asttokens==3.0.1
av==17.0.1
beautifulsoup4==4.14.3
biopython==1.87
blinker==1.7.0
certifi==2025.11.12
charset-normalizer==3.4.7
chess==1.11.2
click==8.3.3
cloup==3.0.9
coingecko-sdk==1.14.2
contourpy==1.3.3
control==0.10.2
cryptography==41.0.7
cuda-bindings==13.2.0
cuda-pathfinder==1.5.4
cuda-toolkit==13.0.2
cycler==0.12.1
cypari==2.5.6
dbus-python==1.3.2
decorator==5.2.1
defusedxml==0.7.1
distro-info==1.7+build1
distro==1.9.0
ecdsa==0.19.2
et-xmlfile==2.0.0
executing==2.2.1
filelock==3.29.0
flatbuffers==25.12.19
fonttools==4.62.1
fsspec==2026.3.0
glcontext==3.0.0
h11==0.16.0
h5py==3.16.0
httpcore==1.0.9
httplib2==0.20.4
httpx==0.28.1
idna==3.13
iniconfig==2.3.0
ipython-pygments-lexers==1.1.1
ipython==9.13.0
isosurfaces==0.1.2
jedi==0.19.2
jinja2==3.1.6
kiwisolver==1.5.0
knot-floer-homology==1.2.1
launchpadlib==1.11.0
lazr.restfulclient==0.14.6
lazr.uri==1.0.6
low-index==1.2.1
lxml==6.1.0
magika==0.6.3
manim==0.20.1
manimpango==0.6.1
mapbox-earcut==2.0.0
markdown-it-py==4.0.0
markdownify==1.2.2
markitdown==0.1.5
markupsafe==3.0.3
matplotlib-inline==0.2.1
matplotlib==3.10.9
mdurl==0.1.2
mido==1.3.3
moderngl-window==3.1.1
moderngl==5.12.0
mpmath==1.3.0
narwhals==2.20.0
networkx==3.6.1
numpy==2.4.4
nvidia-cublas==13.1.0.3
nvidia-cuda-cupti==13.0.85
nvidia-cuda-nvrtc==13.0.88
nvidia-cuda-runtime==13.0.96
nvidia-cudnn-cu13==9.19.0.56
nvidia-cufft==12.0.0.61
nvidia-cufile==1.15.1.6
nvidia-curand==10.4.0.35
nvidia-cusolver==12.0.4.66
nvidia-cusparse==12.6.3.3
nvidia-cusparselt-cu13==0.8.0
nvidia-nccl-cu13==2.28.9
nvidia-nvjitlink==13.0.88
nvidia-nvshmem-cu13==3.4.5
nvidia-nvtx==13.0.85
oauthlib==3.2.2
onnxruntime==1.25.1
openpyxl==3.1.5
packaging==24.0
pandas==3.0.2
parso==0.8.6
patsy==1.0.2
pdf2image==1.17.0
pdfminer-six==20251230
pdfplumber==0.11.9
pexpect==4.9.0
pickleshare==0.7.5
pillow==12.2.0
pip==24.0
plink==2.4.9
plotly==6.7.0
pluggy==1.6.0
polygon-api-client==0.0.0
prompt-toolkit==3.0.52
protobuf==7.34.1
psutil==7.2.2
ptyprocess==0.7.0
pubchempy==1.0.5
pulp==3.3.0
pure-eval==0.2.3
pycairo==1.29.0
pydantic-core==2.46.3
pydantic==2.13.3
pydub==0.25.1
pyerfa==2.0.1.5
pygame==2.6.1
pyglet==2.1.14
pyglm==2.8.3
pygments==2.17.2
pyparsing==3.1.1
pypdf==6.10.2
pypdfium2==5.7.1
pypng==0.20220715.0
pyscf==2.13.0
pytesseract==0.3.13
pytest==9.0.3
python-apt==2.7.7+ubuntu5.2
python-dateutil==2.9.0.post0
python-docx==1.2.0
python-dotenv==1.2.2
python-pptx==1.0.2
pyx==0.17
pyxlsb==1.0.10
qutip==5.2.3
rdkit==2026.3.1
reportlab==4.4.10
requests==2.33.1
rich==15.0.0
scipy==1.17.1
screeninfo==0.8.1
seaborn==0.13.2
setuptools==68.1.2
six==1.16.0
skia-pathops==0.9.2
snappy-manifolds==1.4
snappy==3.3.2
sniffio==1.3.1
soupsieve==2.8.3
spherogram==2.4.1
srt==3.5.3
stack-data==0.6.3
statsmodels==0.14.6
svgelements==1.9.6
sympy==1.14.0
tkinter-gl==1.1
torch==2.11.0
tqdm==4.67.3
traitlets==5.14.3
triton==3.6.0
typing-extensions==4.15.0
typing-inspection==0.4.2
unattended-upgrades==0.1
urllib3==2.6.3
wadllib==1.3.6
watchdog==6.0.0
wcwidth==0.6.0
websockets==14.2
wheel==0.42.0
xlsxwriter==3.2.9
```

## What this app actually uses

- **Runtime**: Python 3.10+ standard library only (`requirements.md` R1.2).
- **Deployable artifact**: built by `make package` (see `tools/package.py`). Contains `scripts/`, an empty schema-only `db/datasource.db`, and the top-level `Makefile`.
- **Dev-time tests**: `pytest==9.0.3` + `coverage==7.6.10` for the test runner / coverage report. Neither is deployed.
- **Dev-time linting**: `ruff==0.14.4` + `mypy==1.19.0`. Neither is deployed.
- **Property testing**: seeded `random` from stdlib. No `hypothesis`.

If you ever find yourself reaching for a third-party import inside `scripts/`, stop — the runtime rule is strict for a reason. On the dev side (`tests/`, `tools/`, `requirements-dev.txt`, `pyproject.toml`), use whatever makes the work smooth.
