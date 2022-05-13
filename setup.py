"""" Setup """
from pathlib import Path

from setuptools import setup

this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup(
    name="hackaru_timular",
    version="0.1.0",
    description="Track your time with the Timular cube and Hackaru",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/pSub/hackaru-timeular",
    author="Pascal Wittmann",
    author_email="github@pascal-wittmann.de",
    license="MIT",
    packages=["hackaru_timeular"],
    install_requires=["bleak", "recordclass", "appdirs", "requests", "PyYAML"],
    entry_points={
        "console_scripts": ["hackaru-timular=hackaru_timeular:main"],
    },
)
