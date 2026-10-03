"""Reproducible builds and container commands. No credentials are recorded."""
import argparse
import os
from pathlib import Path
import subprocess
from tools.common import ROOT

LANGUAGES = ('go', 'java', 'csharp', 'node', 'python', 'rust')
DOCKER = ['docker', '--host=unix:///var/run/docker.sock']


def build(language):
    args = DOCKER + ['build', '--provenance=false']
    if os.getenv('CODEX_PROXY_CERT'):
        args += ['--secret', 'id=proxy_ca,src=' + os.environ['CODEX_PROXY_CERT']]
    if language == 'downstream':
        args += ['-f', 'tools/Dockerfile.downstream', '-t', 'hc-downstream', '.']
    else:
        args += ['-t', 'hc-' + language, str(ROOT / 'services' / language)]
    subprocess.run(args, cwd=ROOT, check=True)


def run_args(language, cpus, downstream, name='hc-sut', port=8080, network=None):
    args = ['run', '-d', '--name', name, '--cpus', str(cpus), '--memory', '4g', '--memory-swap', '4g', '--ulimit', 'nofile=1048576:1048576',
            '-p', f'{port}:8080', '-e', f'DOWNSTREAM_URL={downstream}', '-e', f'WORKERS={cpus}',
            '-e', f'GOMAXPROCS={cpus}', '-e', f'DOTNET_PROCESSOR_COUNT={cpus}',
            '-e', f'TOKIO_WORKER_THREADS={cpus}']
    if language == 'java':
        args += ['-e', f'JAVA_TOOL_OPTIONS=-XX:ActiveProcessorCount={cpus} -Djdk.httpclient.disableRetryConnect=true -Djdk.httpclient.enableAllMethodRetry=false -Djdk.httpclient.redirects.retrylimit=1']
    if network:
        args += ['--network', network]
    return args + ['hc-' + language]


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('languages', nargs='*', default=[*LANGUAGES, 'downstream'])
    args = p.parse_args()
    for language in args.languages:
        if language not in (*LANGUAGES, 'downstream'):
            p.error('Unknown language: ' + language)
        build(language)
