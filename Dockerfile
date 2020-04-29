FROM python:alpine3.7
COPY . .
WORKDIR /
RUN pip install -r requirements.txt
EXPOSE 8000
CMD python ./app.py