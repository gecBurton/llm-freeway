# LLM Freeway

llm-freeway is a simple, secure and open-source proxy server for litellm.

![image](https://github.com/user-attachments/assets/74f1cfdc-5ace-4f61-b720-f21b5a316288)


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
