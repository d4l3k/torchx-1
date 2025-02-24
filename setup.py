#!/usr/bin/env python3
# Copyright (c) Facebook, Inc. and its affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import os
import re
import sys

from setuptools import find_packages, setup


def get_version():
    # get version string from version.py
    # TODO: ideally the version.py should be generated when setup is run
    version_file = os.path.join(os.path.dirname(__file__), "torchx/version.py")
    version_regex = r"__version__ = ['\"]([^'\"]*)['\"]"
    with open(version_file, "r") as f:
        version = re.search(version_regex, f.read(), re.M).group(1)
        return version


if __name__ == "__main__":
    if sys.version_info < (3, 8):
        sys.exit("python >= 3.8 required for torchx-sdk")

    with open("README.md", encoding="utf8") as f:
        readme = f.read()

    with open("requirements.txt") as f:
        reqs = f.read()

    with open("dev-requirements.txt") as f:
        dev_reqs = f.read()

    version = get_version()
    print("-- Building version: " + version)

    setup(
        # Metadata
        name="torchx",
        version=version,
        author="TorchX Devs",
        author_email="torchx@fb.com",
        description="TorchX SDK and Components",
        long_description=readme,
        long_description_content_type="text/markdown",
        url="https://github.com/pytorch/torchx",
        license="BSD-3",
        keywords=["pytorch", "machine learning"],
        python_requires=">=3.8",
        install_requires=reqs.strip().split("\n"),
        include_package_data=True,
        packages=find_packages(exclude=("examples", "*.test", "aws*", "*.fb")),
        test_suite="torchx.test.suites.unittests",
        entry_points={
            "console_scripts": [
                "torchx=torchx.cli.main:main",
            ],
        },
        extras_require={
            "kfp": ["kfp==1.6.2"],
            "dev": dev_reqs,
        },
        # PyPI package information.
        classifiers=[
            "Development Status :: 4 - Beta",
            "Intended Audience :: Developers",
            "Intended Audience :: Science/Research",
            "License :: OSI Approved :: BSD License",
            "Programming Language :: Python :: 3",
            "Programming Language :: Python :: 3.8",
            "Topic :: Scientific/Engineering :: Artificial Intelligence",
        ],
    )
