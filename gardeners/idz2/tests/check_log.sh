#!/bin/sh
# check_log.sh ЛОГ — проверка инвариантов задачи по журналу событий:
#  1) два садовника не занимают одну клетку (с учётом занятости обеих
#     клеток во время перехода);
#  2) недоступные клетки не посещаются и не обрабатываются;
#  3) клетка обрабатывается не более одного раза;
#  4) каждое «начал обработку» закрыто «закончил» или «прервана»;
#  5) число «закончил» совпадает с итоговой статистикой;
#  6) в логе есть итог.
log=$1
[ -f "$log" ] || { echo "нет файла $log"; exit 2; }
dims=$(grep -m1 -o 'Сад [0-9]* x [0-9]*' "$log" | grep -o '[0-9][0-9]*' | tr '\n' ' ')
set -- $dims
H=$1
W=$2
[ -n "$H" ] && [ -n "$W" ] || { echo "нет строки с размерами сада"; exit 2; }
awk -v H="$H" -v W="$W" '
function viol(m) { print "НАРУШЕНИЕ строка " NR ": " m; bad = 1 }
function cells(s, arr,   n) {
  n = 0
  while (match(s, /\([0-9]+,[0-9]+\)/)) { n++; arr[n] = substr(s, RSTART, RLENGTH); s = substr(s, RSTART + RLENGTH) }
  return n
}
/начальное состояние сада/ { mapleft = H; row = 0; next }
mapleft > 0 {
  line = substr($0, 5)
  for (c = 0; c < W; c++) { ch = substr(line, 1 + 2 * c, 1); if (ch == "#" || ch == "~") ob[sprintf("(%d,%d)", row + 1, c + 1)] = 1 }
  row++; mapleft--; next
}
/Садовник [12]:/ {
  match($0, /Садовник [12]:/); g = substr($0, RSTART + RLENGTH - 2, 1) + 0; o = 3 - g
  n = cells($0, a)
  if ($0 ~ /приступил к работе/) {
    if (a[1] in ob) viol("старт в препятствии " a[1])
    if (a[1] == h1[o] || a[1] == h2[o]) viol("старт в клетке соседа " a[1])
    h1[g] = a[1]; h2[g] = ""; pos[g] = a[1]
  } else if ($0 ~ / переходит /) {
    if (a[2] in ob) viol("переход в препятствие " a[2])
    if (a[2] == h1[o] || a[2] == h2[o]) viol("вход в клетку, занятую соседом " a[2])
    if (a[1] != pos[g]) viol("переход не из текущей клетки " a[1] " (стоит в " pos[g] ")")
    h1[g] = a[1]; h2[g] = a[2]
  } else if ($0 ~ / прибыл в /) {
    h1[g] = a[1]; h2[g] = ""; pos[g] = a[1]
  } else if ($0 ~ /начал обработку клетки/) {
    if (a[1] in ob) viol("обработка препятствия " a[1])
    if (a[1] != pos[g]) viol("обработка не в своей клетке " a[1])
    if (a[1] in started) viol("клетка обработана повторно " a[1])
    started[a[1]] = 1; nstart++
  } else if ($0 ~ /закончил обработку клетки/) {
    nfin++
  } else if ($0 ~ /обработка клетки .* прервана/) {
    nabort++
  } else if ($0 ~ /завершает работу/) {
    h1[g] = ""; h2[g] = ""; pos[g] = ""
  }
  next
}
/Обработано клеток: [0-9]+ из/ { match($0, /: [0-9]+/); sumdone = substr($0, RSTART + 2, RLENGTH - 2) + 0; havesum = 1 }
END {
  if (!havesum) viol("в логе нет итоговой статистики")
  else if (nfin != sumdone) viol("«закончил» " nfin " != итог " sumdone)
  if (nstart != nfin + nabort) viol("начато " nstart " != закончено " nfin " + прервано " nabort)
  exit bad
}' "$log"
