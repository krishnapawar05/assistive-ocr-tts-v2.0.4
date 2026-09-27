"""`python app.py` must build the pipeline once. uvicorn.run("app:app") re-imported app.py as a
second module and built a second pipeline, loading every model twice (found in runtime validation)."""
import json
import os
import runpy
import sys
import tempfile
import unittest
from unittest import mock

from tests.helpers import default_config

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class AppMainTest(unittest.TestCase):
    def test_python_app_py_builds_one_pipeline(self):
        cfg = default_config()
        for engine in cfg["ocr"]["engines"].values():  # no models needed to count pipeline builds
            engine["enabled"] = False
        cfg["tts"]["engines"]["coqui"]["enabled"] = False
        cfg["tts"]["volume"] = 0.0
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
            import core.pipeline
            real_init = core.pipeline.AssistivePipeline.__init__
            built = []

            def counting_init(self, *a, **k):
                built.append(self)
                real_init(self, *a, **k)

            with mock.patch.dict(os.environ, {"SVA_CONFIG": path}), \
                    mock.patch.object(core.pipeline.AssistivePipeline, "__init__", counting_init), \
                    mock.patch("uvicorn.run") as run, self.assertLogs("ocr.service", level="ERROR"):
                saved = sys.modules.pop("app", None)
                try:
                    ns = runpy.run_path(os.path.join(ROOT, "app.py"), run_name="__main__")
                    served = run.call_args.args[0]
                    self.assertIs(served, ns["app"], "uvicorn must get the app object, not an import string")
                    if isinstance(served, str):  # what uvicorn would do with an import string
                        __import__(served.split(":")[0])
                    self.assertEqual(len(built), 1)
                finally:
                    for p in built:
                        p.shutdown()
                    sys.modules.pop("app", None)
                    if saved is not None:
                        sys.modules["app"] = saved


if __name__ == "__main__":
    unittest.main()
