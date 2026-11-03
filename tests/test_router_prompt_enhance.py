import json
import os
import sys
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("pe_test_modules")
package.__path__ = [str(ROOT / "modules")]
sys.modules[package.__name__] = package
from pe_test_modules import prompt_enhance as node_module  # noqa: E402
from pe_test_modules import t2i_pe_core as pe  # noqa: E402


def response_for(user_message):
    if "CURRENT SHARD TASK: A" in user_message:
        return {
            "artifact_type": "text_led_graphic",
            "subjects": [{"clothing": "shirt"}],
            "subject_details": "details",
        }
    if "CURRENT SHARD TASK: B" in user_message:
        return {
            "background_setting": "scene",
            "quadrant_scan": "layout",
            "resolution": {"H": 2048, "W": 2048},
            "aspect_ratio": "1:1",
        }
    if "CURRENT SHARD TASK: C" in user_message:
        return {
            "artifact_type": "text_led_graphic",
            "lighting": {"conditions": "light"},
            "aesthetics": {"composition": "grid"},
            "cinematography": {"framing": "wide"},
            "style_medium": "vector",
            "artistic_style": "flat",
        }
    if "CURRENT SHARD TASK: D" in user_message:
        return {"context": "poster", "text_and_signage_elements": []}
    raise AssertionError(user_message)


def fake_call(**kwargs):
    response = response_for(kwargs["user_message"])
    return response, {"prompt_tokens": 10, "completion_tokens": 20}, "stop", json.dumps(response)


class RouterPromptEnhanceTest(unittest.TestCase):
    def setUp(self):
        self.node = node_module.RouterPromptEnhance()
        self.args = dict(
            user_prompt="A poster",
            mode="full",
            system_prompt="custom system",
            shard_a_subjects=pe.A_SUBJECTS_PROMPT,
            shard_b_spatial=pe.B_SPATIAL_PROMPT,
            shard_c_direction=pe.C_DIRECTION_PROMPT,
            shard_d_delivery=pe.D_DELIVERY_PROMPT,
            canvas_mode="explicit",
            width=2720,
            height=1536,
            aspect_ratio="16:9",
            base_url="https://example.invalid/v1",
            model="test-model",
            max_tokens=2048,
            reasoning_effort="none",
            service_tier="priority",
            timeout=10,
            retries=1,
            run_id=0,
        )
        self.environment = patch.dict(os.environ, {"PROMPT_UPSAMPLER_API_KEY": "secret"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    @patch.object(pe, "chat_completion", side_effect=fake_call)
    def test_full_path_merges_and_exposes_actual_messages(self, call):
        enhanced, report, shards = self.node.enhance(**self.args)
        result, report, shards = json.loads(enhanced), json.loads(report), json.loads(shards)
        self.assertEqual(call.call_count, 4)
        self.assertEqual(result["resolution"], {"H": 1536, "W": 2720})
        self.assertEqual(result["aspect_ratio"], "16:9")
        self.assertEqual(result["subjects"][0]["clothing"], "")
        self.assertEqual(result["lighting"], pe.FLAT_GRAPHIC_DIRECTION["lighting"])
        self.assertTrue(report["c_direction_overridden"])
        self.assertEqual(shards["a_subjects"]["system_prompt"], "custom system")
        self.assertIn("A poster", shards["a_subjects"]["user_message"])
        self.assertEqual(
            json.loads(shards["a_subjects"]["raw_response"])["artifact_type"], "text_led_graphic"
        )
        self.assertNotIn("secret", enhanced + json.dumps(report) + json.dumps(shards))

    @patch.object(pe, "chat_completion", side_effect=fake_call)
    def test_single_shard_cannot_return_complete_prompt(self, call):
        self.args.update(mode="b_spatial", canvas_mode="auto")
        enhanced, report, shards = self.node.enhance(**self.args)
        self.assertEqual(enhanced, "")
        self.assertEqual(json.loads(report)["status"], "partial")
        self.assertEqual(list(json.loads(shards)), ["b_spatial"])
        self.assertIn(pe.AUTO_CANVAS_GUIDANCE, call.call_args.kwargs["user_message"])
        self.assertEqual(call.call_count, 1)

    @patch.object(pe, "chat_completion", side_effect=fake_call)
    def test_invalid_template_fails_before_requests(self, call):
        self.args["shard_d_delivery"] = "no marker"
        with self.assertRaisesRegex(ValueError, "marker"):
            self.node.enhance(**self.args)
        call.assert_not_called()

    @patch.object(pe, "chat_completion", side_effect=fake_call)
    def test_simultaneous_configurations_remain_isolated(self, call):
        def run(system):
            return json.loads(self.node.enhance(**{**self.args, "system_prompt": system})[2])

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, ["system A", "system B"]))
        for result, expected in zip(results, ["system A", "system B"]):
            self.assertTrue(all(shard["system_prompt"] == expected for shard in result.values()))


class ModelDiscoveryTest(unittest.TestCase):
    def setUp(self):
        from pe_test_modules import model_discovery

        self.discovery = model_discovery
        self.env = patch.dict(
            os.environ,
            {
                "PROMPT_UPSAMPLER_API_KEY": "test-secret",
                "PROMPT_UPSAMPLER_BASE_URL": "https://example.invalid/v1",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_fetches_ids_using_server_key(self):
        from io import BytesIO
        from unittest.mock import MagicMock

        response = BytesIO(b'{"data":[{"id":"model-a"},{"id":"model-b"},{"id":"model-a"}]}')
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        with patch.object(self.discovery, "build_opener", return_value=opener):
            self.assertEqual(
                self.discovery.get_models("https://example.invalid/v1"), ["model-a", "model-b"]
            )
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.invalid/v1/models")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-secret")

    def test_rejects_unconfigured_host_before_sending_key(self):
        with patch.object(self.discovery, "build_opener") as opener:
            with self.assertRaisesRegex(ValueError, "PROMPT_UPSAMPLER_BASE_URL"):
                self.discovery.get_models("https://example.net/v1")
            opener.assert_not_called()


class DotenvConfigTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        from pe_test_modules import pe_config

        self.config = pe_config
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.path = Path(self.tempdir.name) / ".env"
        path_patch = patch.object(pe_config, "DOTENV_PATH", self.path)
        path_patch.start()
        self.addCleanup(path_patch.stop)
        env_patch = patch.dict(os.environ, {}, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)

    def test_reads_node_dotenv_without_exporting_to_process(self):
        self.path.write_text("export PROMPT_UPSAMPLER_API_KEY='local # secret'\n"
                             "PROMPT_UPSAMPLER_BASE_URL=https://example.test/v1 # comment\n"
                             "PROMPT_UPSAMPLER_MODEL=local-model\n")
        self.assertEqual(self.config.get_api_key(), "local # secret")
        self.assertEqual(self.config.get_config("PROMPT_UPSAMPLER_BASE_URL"), "https://example.test/v1")
        self.assertEqual(self.config.get_config("PROMPT_UPSAMPLER_MODEL"), "local-model")
        self.assertNotIn("PROMPT_UPSAMPLER_API_KEY", os.environ)

    def test_process_environment_overrides_and_missing_file_is_safe(self):
        self.assertEqual(self.config.get_config("PROMPT_UPSAMPLER_MODEL"), "")
        self.path.write_text("PROMPT_UPSAMPLER_MODEL=file-model\n")
        os.environ["PROMPT_UPSAMPLER_MODEL"] = "env-model"
        self.assertEqual(self.config.get_config("PROMPT_UPSAMPLER_MODEL"), "env-model")

    def test_discovery_uses_node_dotenv_key_and_url(self):
        from io import BytesIO
        from unittest.mock import MagicMock

        from pe_test_modules import model_discovery

        self.path.write_text("PROMPT_UPSAMPLER_API_KEY=file-secret\n"
                             "PROMPT_UPSAMPLER_BASE_URL=https://example.test/v1\n")
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = BytesIO(b'{"data":[{"id":"model-a"}]}')
        with patch.object(model_discovery, "build_opener", return_value=opener):
            self.assertEqual(model_discovery.get_models(), ["model-a"])
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.test/v1/models")
        self.assertEqual(request.get_header("Authorization"), "Bearer file-secret")


if __name__ == "__main__":
    unittest.main()
