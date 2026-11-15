import os
import secrets
import subprocess
import sys
import time

name = 'smart-reporting-semantic-test-' + secrets.token_hex(5)
password = secrets.token_hex(24)
subprocess.run(['docker','run','--rm','-d','--name',name,'-p','127.0.0.1::5432','-e','POSTGRES_PASSWORD='+password,'-e','POSTGRES_DB=semantic_isolated','docker.m.daocloud.io/pgvector/pgvector:pg16'], check=True, stdout=subprocess.DEVNULL)
try:
    port = subprocess.check_output(['docker','port',name,'5432/tcp'],text=True).strip().rsplit(':',1)[1]
    for _ in range(100):
        ready = subprocess.run(['docker','exec',name,'pg_isready','-U','postgres','-d','semantic_isolated'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if ready.returncode == 0: break
        time.sleep(.1)
    else: raise RuntimeError('isolated PG readiness failed')
    env = dict(os.environ)
    base=f'postgresql://postgres:{password}@127.0.0.1:{port}/semantic_isolated'
    env.update(AGENT_ENV_FILE='/dev/null', REPORTING_MANAGEMENT_TEST_DB_URL=base.replace('postgresql:', 'postgresql+psycopg:'), REPORTING_KNOWLEDGE_TEST_DB_URL=base.replace('postgresql:', 'postgresql+psycopg:'))
    result = subprocess.run([sys.executable,'-m','pytest',*sys.argv[1:]],env=env)
finally:
    stopped=subprocess.run(['docker','stop',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    print('isolated_vector_database_cleanup='+str(stopped.returncode==0),flush=True)
sys.exit(result.returncode)
