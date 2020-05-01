FROM python:alpine3.7
COPY . .
WORKDIR /
RUN pip install --upgrade pip
RUN pip install -r requirements.txt
CMD python ./app.py