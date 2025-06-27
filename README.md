# this is a just-for-fun project, feel free to copy but do not use this as-is!

## LLM Freeway

llm-freeway is a simple, secure and open-source proxy server for litellm.

![image](https://github.com/user-attachments/assets/74f1cfdc-5ace-4f61-b720-f21b5a316288)

## Data

* models loaded from json on disk/s3
* user data from KeyCloak (Cognito will be added)
* logs to Elastic/OpenSearch/postgres


## features

* chat-completion
  * authorization via jwt
  * streaming and non-streaming
* user management
  * Create Read Update and Delete users
  * Generate tokens for use with chat-completion 
  * Restrict user access by:
    * tokens-per-minute
    * requests-per-minute
    * USD-per-month
* logs
  * access to your own logs
  * access all logs if you are and admin


## how to run

* locally, using sqlite `make web`
* via docker `docker compose up web`


## tested in anger with

* azure/gpt
* bedrock/anthropic
* google/vertex-ai 
