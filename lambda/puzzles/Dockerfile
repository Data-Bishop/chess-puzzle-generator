FROM public.ecr.aws/lambda/python:3.12

# Install tar (not present in the Lambda base image) then fetch Stockfish
RUN dnf install -y tar && dnf clean all

RUN curl -fsSL \
    "https://github.com/official-stockfish/Stockfish/releases/download/sf_17/stockfish-ubuntu-x86-64-avx2.tar" \
    -o /tmp/stockfish.tar \
    && tar -xf /tmp/stockfish.tar -C /tmp \
    && mv /tmp/stockfish/stockfish-ubuntu-x86-64-avx2 /usr/local/bin/stockfish \
    && chmod +x /usr/local/bin/stockfish \
    && rm -rf /tmp/stockfish /tmp/stockfish.tar

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy handler
COPY handler.py ${LAMBDA_TASK_ROOT}/

CMD ["handler.handler"]
