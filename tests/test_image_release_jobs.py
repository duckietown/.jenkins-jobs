from collections import defaultdict
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("image_release_jobs", ROOT / "generator/create_image_release_jobs.py")
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)
TOOLS = "a" * 40


class ImageReleaseJobTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="jenkins-release-jobs-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.jobs = self.root / "jobs"
        template = self.jobs / "__image_release_template__"
        template.mkdir(parents=True)
        shutil.copyfile(
            ROOT / "jobs/__image_release_template__/config.xml.template", template / "config.xml.template",
        )
        self.repositories = self.root / "repositories.json"
        shutil.copyfile(ROOT / "repositories.json", self.repositories)

    def test_missing_tools_pin_generates_two_disabled_manual_jobs(self):
        paths = generator.generate(self.jobs, self.repositories, "")
        self.assertEqual(2, len(paths))
        for path in paths:
            document = ET.parse(path).getroot()
            self.assertEqual("flow-definition", document.tag)
            self.assertEqual("true", document.findtext("disabled"))
            self.assertEqual([], list(document.find("triggers")))
            self.assertIsNotNone(document.find(".//org.jenkinsci.plugins.workflow.job.properties.DisableConcurrentBuildsJobProperty"))
            self.assertNotRegex(path.read_text(), r"@[A-Z_]+@")

    def test_only_pinned_tools_enable_jobs_with_scoped_offline_signing(self):
        paths = generator.generate(self.jobs, self.repositories, TOOLS)
        for path in paths:
            with self.subTest(job=path.parent.name):
                document = ET.parse(path).getroot()
                self.assertEqual("false", document.findtext("disabled"))
                script = document.findtext("definition/script")
                self.assertIn(f"def toolsRef = '{TOOLS}'", script)
                self.assertIn("submitter: 'duckietown-release-managers'", script)
                self.assertEqual(2, script.count("node('artifact-signing')"))
                self.assertEqual(2, script.count("node('docker-release')"))
                self.assertEqual(2, script.count("variable: 'ARTIFACT_KEY'"))
                self.assertNotIn("DUCKIETOWN_CI_DT_TOKEN", script)
                self.assertNotIn("--push", script)
                self.assertIn("archiveArtifacts", script)
                self.assertLess(script.index("stage('Maintainer approval')"), script.index("withCredentials([file"))
                self.assertLess(script.index("dt-ci-image-release finalize"), script.index("credentialsId: 'PRODUCTION_DOCKER_PASSWORD'"))
                for shell in re.findall(r"sh '''(.*?)'''", script, flags=re.S):
                    result = subprocess.run(["bash", "-n"], input=shell, text=True, capture_output=True)
                    self.assertEqual(0, result.returncode, result.stderr)

    def test_moving_or_injected_tools_refs_are_rejected_before_writing(self):
        for ref in ("main", "a" * 39, "A" * 40, "';error('bad')"):
            with self.subTest(ref=ref), self.assertRaisesRegex(ValueError, "full lowercase"):
                generator.generate(self.jobs, self.repositories, ref)
        self.assertEqual([], list(self.jobs.glob("Protected Image Release*")))

    def test_duplicate_or_substituted_components_fail_before_writing(self):
        repositories = json.loads(self.repositories.read_text())
        selected = [value for value in repositories if "release_component" in value]
        self.repositories.write_text(json.dumps(selected + [selected[0]]))
        with self.assertRaisesRegex(ValueError, "exactly once"):
            generator.generate(self.jobs, self.repositories, TOOLS)
        selected[0]["origin"] = "someone/another-repository"
        self.repositories.write_text(json.dumps(selected))
        with self.assertRaisesRegex(ValueError, "approved Duckietown"):
            generator.generate(self.jobs, self.repositories, TOOLS)
        self.assertEqual([], list(self.jobs.glob("Protected Image Release*")))

    def test_autobuild_template_formats_and_smokes_images_without_source_sessions(self):
        template = (ROOT / "jobs/__autobuild_template__/config.xml.template").read_text()
        for repository in ("dt-duckiematrix", "dt-duckietown-viewer", "dt-commons"):
            for distro in ("ente", "ente-staging", "daffy"):
                params = defaultdict(str, {
                    "REPO_NAME": repository, "REPO_DISTRO": distro,
                    "REPO_ARCH": "arm64v8", "TAG": distro.split("-")[0],
                    "DOCKER_REGISTRY": "docker.io", "DUCKIETOWN_CI_DTSHELL_PROFILE": distro,
                })
                document = ET.fromstring(template.format_map(params))
                shell = document.findtext("builders/hudson.tasks.Shell/command")
                result = subprocess.run(["bash", "-n"], input=shell, text=True, capture_output=True)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("exec dt-launcher-ci-smoke-test", shell)
                self.assertIn("devel run", shell)
                case, = re.findall(r'    case "' + repository + r'" in.*?    esac', shell, flags=re.S)
                result = subprocess.run(
                    ["bash", "-c", """
docker() { printf 'DOCKER'; printf '<%s>' "$@"; }
dts() { printf 'DTS'; printf '<%s>' "$@"; }
BUILD_MACHINE=fixture:2376
""" + case], text=True, capture_output=True,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                if repository == "dt-commons":
                    self.assertTrue(result.stdout.startswith("DTS<"), result.stdout)
                    self.assertIn("<devel><run>", result.stdout)
                else:
                    self.assertTrue(result.stdout.startswith("DOCKER<"), result.stdout)
                    self.assertIn("<--host><tcp://fixture:2376><run><--rm>", result.stdout)
                    self.assertIn("exec dt-launcher-ci-smoke-test", result.stdout)
                    self.assertNotIn("<devel><run>", result.stdout)

    def test_tracked_application_jobs_use_the_image_only_smoke_path(self):
        for repository in ("dt-duckiematrix", "dt-duckietown-viewer"):
            for arch in ("amd64", "arm64v8"):
                path = ROOT / f"jobs/Docker Autobuild - ente - {repository} - {arch}/config.xml"
                shell = ET.parse(path).findtext("builders/hudson.tasks.Shell/command")
                self.assertIn(f'case "{repository}" in', shell)
                self.assertIn(f'"docker.io/duckietown/{repository}:ente-{arch}"', shell)
                result = subprocess.run(["bash", "-n"], input=shell, text=True, capture_output=True)
                self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
