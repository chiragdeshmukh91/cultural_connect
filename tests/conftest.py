import os
import tempfile

# Configure an isolated environment BEFORE any backend module is imported.
_tmp = tempfile.mkdtemp(prefix="cc-test-")
os.environ["DB_PATH"] = os.path.join(_tmp, "boot.db")
os.environ["QLOO_API_KEY"] = "test-key-not-real"
os.environ["QLOO_BASE_URL"] = "http://127.0.0.1:9"  # unroutable: any un-faked Qloo call fails loudly
os.environ["LLM_PROVIDER"] = "none"
