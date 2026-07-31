FROM python:3.13-slim

RUN pip install --no-cache-dir cryptography==45.0.5

COPY decrypt_slrec.py /opt/decrypt_slrec.py
ENTRYPOINT ["python", "/opt/decrypt_slrec.py"]
