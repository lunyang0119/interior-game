# Copied unchanged from the Discord bot repo (fugitive/), commit 2182a11. Do not edit here; the engine is the single source of truth.
"""Korean particle helpers (the two functions the train game needs from the bot's utils.py)."""


def get_korean_particle(word: str, particle_batchim: str, particle_no_batchim: str) -> str:
    """한글 단어의 마지막 글자 받침 유무로 조사 선택 (예: '이'/'가', '을'/'를').

    한글이 아닌 글자로 끝나면 particle_no_batchim 을 돌려준다.
    """
    if not word:
        return particle_no_batchim
    last_char = word[-1]
    if '가' <= last_char <= '힣':
        if (ord(last_char) - ord('가')) % 28 == 0:
            return particle_no_batchim
        return particle_batchim
    return particle_no_batchim


def ends_with_hangul(word: str) -> bool:
    return bool(word) and '가' <= word[-1] <= '힣'
