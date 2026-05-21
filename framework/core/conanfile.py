# SPDX-License-Identifier: Apache-2.0

import json
import getpass
import os
import pathlib
import platform
import datetime
import shutil
import stat
import subprocess
import sys

from conan import ConanFile
from conan.tools.files import copy, mkdir, rmdir
from conan.tools.cmake import CMake, CMakeDeps, CMakeToolchain
from conan.tools.scm import Git
from conan.tools.build import can_run
from conan.tools.microsoft import is_msvc
try:
    from distutils import sysconfig
except ImportError:
    import sysconfig
from os import environ
from os import path

with open(path.join("package.json"), "r") as package_json_file:
    package_json = json.load(package_json_file)


class KungfuCoreConan(ConanFile):
    name = "kungfu-core"
    version = package_json["version"]
    settings = "os", "compiler", "build_type", "arch"
    options = {
        "log_level": ["trace", "debug", "info", "warning", "error", "critical"],
        "arch": ["x64"],
        "freezer": ["nuitka", "pyinstaller"],
        "node_version": ["16.15.0", "20.11.0", "24.15.0"],
        "electron_version": ["32.0.0", "28.0.0", "24.0.0"],
        "vs_toolset": ["auto", "ClangCL", "v143"],
        "with_yarn": [True, False],
    }
    default_options = {
        "fmt/*:header_only": True,
        "spdlog/*:header_only": True,
        "spdlog/*:shared": False,
        "sqlite3/*:enable_column_metadata": True,
        "sqlite3/*:enable_json1": True,
        "sqlite3/*:enable_preupdate_hook": True,
        "sqlite3/*:enable_dbstat_vtab": True,
        "sqlite3/*:shared": False,
        "nng/*:http": False,
        "&:log_level": "info",
        "&:arch": "x64",
        "&:freezer": "pyinstaller",
        "&:node_version": "24.15.0",
        "&:electron_version": "32.0.0",
        "&:vs_toolset": "v143",
        "&:with_yarn": True,
    }
    exports = "package.json"
    exports_sources = "src/*", "package.json", "CMakeLists.txt", ".cmake/*"
    conanfile_dir = path.dirname(path.realpath(__file__))
    pyi_hooks_dir = path.join(conanfile_dir, "src", "python", "pyi-hooks")
    build_info_file = "kungfubuildinfo.json"
    build_dir = path.join(conanfile_dir, "build")
    dist_dir = path.join(conanfile_dir, "dist")
    kfc_dir = path.join(dist_dir, "kfc")
    kfs_dir = path.join(dist_dir, "kfs")

    def requirements(self):
        self.requires("fmt/8.1.1")
        self.requires("nlohmann_json/3.11.2")
        self.requires("nng/1.5.2")
        self.requires("rxcpp/4.1.1")
        self.requires("sqlite3/3.39.2")
        self.requires("spdlog/1.10.0")
        self.requires("tabulate/1.4")

    def configure(self):
        if self.settings.os != "Windows":
            self.settings.compiler.libcxx = "libstdc++11"
        else:
            try:
                toolset = str(self.options.vs_toolset)
                if toolset and toolset not in ["auto", "None", "Invalid"]:
                    self.settings.compiler.toolset = toolset
            except Exception:
                pass

    def generate(self):
        from conan.tools.cmake import CMakeToolchain, CMakeDeps
        tc = CMakeToolchain(self)
        tc.generate()
        deps = CMakeDeps(self)
        deps.generate()

    def layout(self):
        self.folders.source = "."
        self.folders.build = "build"
        self.folders.generators = self.folders.build

    def imports(self):
        python_inc_src = sysconfig.get_python_inc(plat_specific=True)
        python_inc_dst = (
            "include"
            if path.basename(python_inc_src) == "include"
            else path.join("include", path.basename(python_inc_src))
        )
        copy(self, "*", python_inc_src, python_inc_dst)
        copy(self, "*", "include", "include")

    def build(self):
        build_type = str(self.settings.build_type)
        self._clean_build_info(build_type)
        self._run_build(build_type, "node")
        self._run_build(build_type, "electron")
        self._gen_build_info(build_type)
        self._show_build_info(build_type)

    def package(self):
        build_type = str(self.settings.build_type)
        if self.conf.get("user.kungfu.gyp_call", default=False):
            self._clean_dist_dir()
            self._run_freeze(build_type)
            self._show_build_info(build_type)
        else:
            copy(self, "*", dst="include", src="src/include")
            copy(self, "*", dst="lib", src=build_type)
            copy(self, "*", dst="bin", src=path.join("src", "libkungfu", build_type))

    def _get_node_version(self, runtime):
        return (
            str(self.options.electron_version)
            if runtime == "electron"
            else str(self.options.node_version)
        )

    def _get_build_info_path(self, build_type):
        return path.join(self.build_dir, build_type, self.build_info_file)

    def _clean_build_info(self, build_type):
        build_info_path = self._get_build_info_path(build_type)
        if path.exists(build_info_path):
            os.remove(build_info_path)
            self.output.info("Deleted kungfubuildinfo.json")

    def _clean_dist_dir(self):
        if path.exists(self.dist_dir):
            def redo_with_write(redo_func, path, err):
                os.chmod(path, stat.S_IWRITE)
                redo_func(path)
            shutil.rmtree(self.dist_dir, onerror=redo_with_write)
            self.output.info("Deleted dist directory")

    def _gen_build_info(self, build_type):
        now = datetime.datetime.now()
        build_info = {
            "version": self.version,
            "pythonVersion": platform.python_version(),
            "build": {
                "user": getpass.getuser(),
                "osVersion": platform.platform(),
                "timestamp": now.strftime("%Y/%m/%d %H:%M:%S"),
            },
        }

        try:
            git = Git(self, self.source_folder)
            build_info["git"] = {
                "tag": git.get_tag(),
                "branch": git.get_branch(),
                "revision": git.get_revision(),
                "pristine": git.is_pristine(),
            }
        except Exception:
            pass

        mkdir(self, path.join(self.build_dir, build_type))
        with open(self._get_build_info_path(build_type), "w") as output:
            json.dump(build_info, output, indent=2)

    def _show_build_info(self, build_type):
        with open(self._get_build_info_path(build_type), "r") as build_info_file:
            build_info = json.load(build_info_file)
            build_version = build_info["version"]
            self.output.success(f"build version {build_version}")

    def _enable_modules(self, runtime):
        modules = {
            "libkungfu": True,
            "kungfu_node": (self.settings.os != "Windows") or (runtime == "electron"),
            "pykungfu": runtime == "node",
        }

        def switch(module):
            environ_key = f"KUNGFU_BUILD_SKIP_{module.upper()}"
            if not modules[module]:
                environ[environ_key] = "on"
            else:
                environ.pop(environ_key, None)

        [switch(key) for key in modules.keys()]

    def _run_build(self, build_type, runtime):
        if f"KUNGFU_BUILD_SKIP_RUNTIME_{runtime.upper()}" in environ:
            self.output.warn(f"disabled build for runtime {runtime}")
            return
        toolset = str(self.options.vs_toolset)
        parallel_opt = (
            []
            if self.settings.os == "Windows"
            else ["--", "-j", f"{os.cpu_count()}"]
        )
        self._enable_modules(runtime)
        if str(self.options.with_yarn) == "True":
            self._run_cmake_js(build_type, "configure", runtime, toolset)
            self._run_cmake_js(build_type, "build", runtime, toolset)
        elif runtime == "node":
            environ["KUNGFU_BUILD_SKIP_KUNGFU_NODE"] = "on"
            environ["KUNGFU_BUILD_SKIP_PYKUNGFU"] = "on"
            cmake = CMake(self)
            cmake.configure(variables={"CMAKE_BUILD_TYPE": "Release", "SPDLOG_LOG_LEVEL_COMPILE": "trace"})
            cmake.build()

    def _run_yarn(self, *args):
        yarn = "yarn" if self.settings.os != "Windows" else "yarn.cmd"
        rc = subprocess.Popen([yarn, *args], cwd=self.conanfile_dir).wait()
        if rc != 0:
            self.output.error(f"yarn {args} failed with return code {rc}")
            sys.exit(rc)

    def _build_cmake_js_cmd(self, build_type, cmd, runtime, toolset):
        spdlog_levels = {
            "trace": "SPDLOG_LEVEL_TRACE",
            "debug": "SPDLOG_LEVEL_DEBUG",
            "info": "SPDLOG_LEVEL_INFO",
            "warning": "SPDLOG_LEVEL_WARN",
            "error": "SPDLOG_LEVEL_ERROR",
            "critical": "SPDLOG_LEVEL_CRITICAL",
        }
        log_level = spdlog_levels[str(self.options.log_level)]

        parallel_level = 1

        python_path = (
            subprocess.Popen(["pipenv", "--py"], stdout=subprocess.PIPE)
            .stdout.read()
            .decode()
            .strip()
        )

        toolset_option = ["--toolset", toolset] if toolset != "auto" else []

        build_option = (
            toolset_option + ["--platform", str(self.options.arch)]
            if self.settings.os == "Windows"
            else ["--parallel", str(parallel_level)]
        )

        debug_option = ["--debug"] if build_type == "Debug" else []

        return (
            [
                "cmake-js",
                "--arch",
                str(self.options.arch),
                "--runtime",
                runtime,
                "--runtime-version",
                self._get_node_version(runtime),
                f"--CDPYTHON_EXECUTABLE={python_path}",
                f"--CDSPDLOG_LOG_LEVEL_COMPILE={log_level}",
                f"--CDCMAKE_BUILD_PARALLEL_LEVEL={parallel_level}",
            ]
            + build_option
            + debug_option
            + [cmd]
        )

    def _run_cmake_js(self, build_type, cmd, runtime, toolset):
        [
            os.environ.pop(env_key)
            for env_key in os.environ
            if env_key.upper().startswith("NPM_")
        ]
        self._run_yarn(*self._build_cmake_js_cmd(build_type, cmd, runtime, toolset))
        self.output.success(f"cmake-js {cmd} done")

    def _run_pyinstaller(self, build_type):
        pathlib.Path(self._get_build_info_path(build_type)).touch()
        from PyInstaller import __main__ as freezer

        freezer.run(
            [
                f"--workpath={path.join('.', 'build')}",
                f"--distpath={path.join('.', 'dist')}",
                "--clean",
                "--noconfirm",
                path.join(".", "src", "python", "kfc.spec"),
            ]
        )

        from wcmatch import glob

        for file in glob.glob("*kfs*", flags=glob.EXTGLOB, root_dir=self.kfs_dir):
            shutil.copy(path.join(self.kfs_dir, file), self.kfc_dir)
        shutil.rmtree(self.kfs_dir)

        self.output.success("PyInstaller done")

    def _run_nuitka(self, build_type):
        self._run_yarn(
            "nuitka",
            "--output-dir=build",
            path.join("src", "python", "kfc.py"),
        )

        kfc_dist_dir = path.join(self.build_dir, "kfc.dist")
        shutil.copytree(build_type, kfc_dist_dir)
        shutil.rmtree(self.kfc_dir)
        shutil.move(kfc_dist_dir, self.kfc_dir)

        self.output.success("Nuitka done")

    def _run_freeze(self, build_type):
        os.environ["KFC_PYI_HOOKS_PATH"] = self.pyi_hooks_dir
        freeze = {"pyinstaller": self._run_pyinstaller, "nuitka": self._run_nuitka}
        freeze[str(self.options.freezer)](build_type)