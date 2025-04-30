# lambda/index.py
import json
import os
import re
import requests
from requests.exceptions import RequestException, Timeout


def extract_region_from_arn(arn):
    match = re.search('arn:aws:lambda:([^:]+):', arn)
    if match:
        return match.group(1)
    return "us-east-1"


FASTAPI_ROOT = os.environ.get(
    "FASTAPI_ROOT", "http://localhost:8000")  # デフォルト値を設定


def validate_conversation_history(history):
    if not isinstance(history, list):
        raise ValueError("conversationHistory must be a list")
    for msg in history:
        if not isinstance(msg, dict):
            raise ValueError(
                "Each message in conversationHistory must be a dictionary")
        if "role" not in msg or "content" not in msg:
            raise ValueError(
                "Each message must have 'role' and 'content' fields")
        if msg["role"] not in ["user", "assistant"]:
            raise ValueError(
                "Message role must be either 'user' or 'assistant'")


def lambda_handler(event, context):
    try:
        print("Received event:", json.dumps(event))

        user_info = None
        if 'requestContext' in event and 'authorizer' in event['requestContext']:
            user_info = event['requestContext']['authorizer']['claims']
            print(
                f"Authenticated user: {user_info.get('email') or user_info.get('cognito:username')}")

        if 'body' not in event:
            raise ValueError("Request body is missing")

        body = json.loads(event['body'])

        if 'message' not in body:
            raise ValueError("Message is required")

        message = body['message']
        conversation_history = body.get('conversationHistory', [])

        validate_conversation_history(conversation_history)

        print("Processing message:", message)

        # 会話履歴をプロンプト形式に変換
        prompt_parts = []
        for m in conversation_history:
            role = "User" if m["role"] == "user" else "Assistant"
            prompt_parts.append(f"{role}: {m['content']}")
        prompt_parts.append(f"User: {message}")
        prompt_parts.append("Assistant:")
        prompt_text = "\n".join(prompt_parts)

        # FastAPI へリクエスト
        print("Sending request to FastAPI at:", FASTAPI_ROOT)
        try:
            api_resp = requests.post(
                f"{FASTAPI_ROOT}/generate",
                json={"prompt": prompt_text, "max_new_tokens": 256},
                timeout=60
            )
            api_resp.raise_for_status()
        except Timeout:
            raise Exception("FastAPI request timed out")
        except RequestException as e:
            raise Exception(f"FastAPI request failed: {str(e)}")

        if api_resp.status_code != 200:
            raise Exception(
                f"FastAPI error {api_resp.status_code}: {api_resp.text}")

        gen_text = api_resp.json().get("generated_text", "")
        assistant_response = re.split(
            r"Assistant:\s*", gen_text, maxsplit=1)[-1].strip()

        messages = conversation_history + [
            {"role": "user", "content": message},
            {"role": "assistant", "content": assistant_response}
        ]

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({
                "success": True,
                "response": assistant_response,
                "conversationHistory": messages
            })
        }

    except json.JSONDecodeError:
        return {
            "statusCode": 400,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({
                "success": False,
                "error": "Invalid JSON format in request body"
            })
        }
    except ValueError as e:
        return {
            "statusCode": 400,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({
                "success": False,
                "error": str(e)
            })
        }
    except Exception as error:
        print("Error:", str(error))
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({
                "success": False,
                "error": str(error)
            })
        }
