#!/bin/bash
# Українізатор Sunless Sea – встановлення для macOS у два кліки.
cd "$(dirname "$0")" || exit 1
xattr -dr com.apple.quarantine . >/dev/null 2>&1

echo
echo "  УКРАЇНІЗАТОР SUNLESS SEA"
echo "  ========================"
echo

finish () {
  echo
  read -r -p "  Готово. Натисни Enter, вікно можна закривати." _
  exit "$1"
}

brew_env () {
  for p in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$p" ] && eval "$("$p" shellenv)" && return 0
  done
  return 1
}

# ---- 1. Python ----
if ! python3 -c "import sys" >/dev/null 2>&1; then
  echo "  Немає Python 3. Відкриваю сторінку завантаження –"
  echo "  постав його і запусти мене ще раз."
  open "https://www.python.org/downloads/macos/" >/dev/null 2>&1
  finish 1
fi

# ---- 2. бібліотеки ----
SUPPORT="$HOME/Library/Application Support/UA-SunlessSea"
VENV="$SUPPORT/venv"
PY="$VENV/bin/python3"

if [ ! -x "$PY" ]; then
  echo "  Готую оточення, це хвилина…"
  mkdir -p "$SUPPORT"
  python3 -m venv "$VENV" >/dev/null 2>&1
fi
if [ -x "$PY" ]; then
  "$PY" -m pip install --quiet --upgrade pip >/dev/null 2>&1
  "$PY" -m pip install --quiet UnityPy fonttools || {
    echo "  Не вдалося поставити бібліотеки. Перевір інтернет і спробуй ще раз."; finish 1; }
else
  PY="python3"
  python3 -m pip install --quiet --user UnityPy fonttools || {
    echo "  Не вдалося поставити бібліотеки. Перевір інтернет і спробуй ще раз."; finish 1; }
fi

# ---- 3. Mono, якщо без нього не обійтись ----
brew_env
NEED_MONO=1
[ -f "data/dll_patch.bin" ] && NEED_MONO=0
command -v mono >/dev/null 2>&1 && NEED_MONO=0

if [ "$NEED_MONO" = "1" ]; then
  echo
  echo "  Переклад меню, вкладок і суднового журналу лежить усередині збірки"
  echo "  гри. Щоб його туди вписати, на маку потрібен Mono. Я поставлю його"
  echo "  сам, разово: близько гігабайта, Термінал спитає пароль від мака."
  echo "  Відмовишся – усе інше однаково перекладеться, англійськими"
  echo "  лишаться тільки меню й журнал."
  echo
  ANS="n"
  if [ -t 0 ]; then read -r -p "  Ставимо? [Y/n] " ANS || ANS="n"; fi
  case "$ANS" in
    [Nn]*) echo "  Гаразд, пропускаю." ;;
    *)
      if ! command -v brew >/dev/null 2>&1; then
        echo "  Ставлю Homebrew…"
        NONINTERACTIVE=1 /bin/bash -c \
          "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        brew_env
      fi
      if command -v brew >/dev/null 2>&1; then
        echo "  Ставлю Mono…"
        brew install mono || echo "  Mono не став. Решта перекладу все одно встановиться."
      else
        echo "  Homebrew не став. Решта перекладу все одно встановиться."
      fi
      ;;
  esac
fi

# ---- 4. власне встановлення ----
echo
"$PY" install.py "$@"
finish $?
