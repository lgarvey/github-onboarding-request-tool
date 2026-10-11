# The recorder: a headless browser to drive the app and ffmpeg to convert the video.
FROM python:3.13-slim

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-inter \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir playwright \
    && playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright

WORKDIR /demo
CMD ["python", "walkthrough.py"]
