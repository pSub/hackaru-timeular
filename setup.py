"""" Setup """
from setuptools import setup

setup(
    name="hackaru_timular",
    version="0.1.0",
    description="Track your time with the Timular cube and Hackaru",
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
