# Set up a base build container and use to install pip dependencies
FROM python:3.9-slim-buster as base
FROM base as builder
RUN mkdir /install
WORKDIR /install
COPY requirements.txt /requirements.txt
RUN pip install --prefix=/install -r /requirements.txt --no-warn-script-location

# Copy over pip dependencies from base
FROM base
COPY --from=builder /install /usr/local

# Set up /app as our runtime directory
RUN mkdir /app
WORKDIR /app

# Run as non-root user
USER nobody

# Add just the files we need to run
ADD app.py ./

CMD python app.py