# Setup Notes: Laptop 2 (Person C - LLM & Evaluation)

- **System Specs**: Core Ultra 7, 32 GB RAM, Intel Arc Graphics
- **Python Version**: Python 3.12.10 (Confirmed)

## 1. Environment Setup

```powershell
# Create & Activate Venv
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install required dependencies
pip install pytest pytest-randomly pytest-repeat ruff pydantic ollama freezegun pandas pyarrow
```

## 2. Ollama & Models Verified

Installed Ollama and pulled two models for comparison:
1. `llama3.2:3b` (3B model, 2.0 GB)
2. `codellama:latest` (7B code-specific model, 3.8 GB)

### Model Benchmark (`"say hi"`)

| Model | Tag | Parameter Size | Latency (CPU) | Output |
| --- | --- | --- | --- | --- |
| Llama 3.2 3B | `llama3.2:3b` | 3B | ~4.39s | "Hi!" |
| CodeLlama 7B | `codellama:latest` | 7B | ~10.59s | "Hello!" |

## 3. Findings
- Ollama runs reliably on CPU for batch evaluation work.
- `llama3.2:3b` provides fast response times (~4.4s) while `codellama:latest` offers dedicated code analysis capability.
