import copy
import logging
from dataclasses import dataclass
from multiprocessing.pool import ThreadPool
from typing import Optional, Sequence, List, Dict, Any, cast

from openai import OpenAI

client = OpenAI()


@dataclass
class OpenAIDecodingArguments:
    max_tokens: int = 2400
    temperature: float = 0.0
    top_p: float = 0.95
    n: int = 1
    stream: bool = False
    stop: Optional[Sequence[str]] = None
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0


DEFAULT_ARGS = OpenAIDecodingArguments()


def openai_completion(
    messages: List[Dict[str, Any]],
    decoding_args: OpenAIDecodingArguments = DEFAULT_ARGS,
    model_name: str = "gpt-4o-mini",
    sleep_time: int = 2,
) -> str:
    decoding_args = copy.deepcopy(decoding_args)
    assert decoding_args.n == 1
    while True:
        try:
            completions = client.chat.completions.create(
                messages=messages, model=model_name, **decoding_args.__dict__)
            break
        except Exception as e:
            logging.warning("OpenAI error: %s.", e)
            if "Please reduce" in str(e):
                decoding_args.max_tokens = int(decoding_args.max_tokens * 0.8)
                logging.warning(
                    "Reducing target length to %d, Retrying...",
                    decoding_args.max_tokens,
                )
            else:
                raise e
    return cast(str, completions.choices[0].message.content.strip())


def openai_batch_completion(
    batch: List[List[Dict[str, Any]]],
    decoding_args: OpenAIDecodingArguments = DEFAULT_ARGS,
    model_name: str = "gpt-4",
    sleep_time: int = 2,
) -> List[str]:
    completions = []
    with ThreadPool(len(batch)) as pool:
        results = pool.starmap(
            openai_completion,
            [(messages, decoding_args, model_name, sleep_time) for messages in batch],
        )
        for result in results:
            completions.append(result)
    return completions
