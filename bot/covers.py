"""Обложки стилей: каталожные кадры товаров с Wildberries.

Кадры отобраны вручную: вещь крупно, по возможности без лица.
Копий у нас нет — только адреса, снимки остаются на серверах WB.
crop=False там, где в кадре нет модели и подрезать верх не нужно.
Протухшие обложки заменяет refresh_examples.py.
"""

COVERS = {
 "minimal": {
  "img": "https://basket-26.wbbasket.ru/vol4782/part478223/478223011/images/c516x688/2.webp",
  "product": "https://www.wildberries.ru/catalog/478223011/detail.aspx",
  "brand": "Befree",
  "name": "Брюки прямые костюмные с разрезами школьные",
  "id": 478223011,
  "crop": true
 },
 "quiet": {
  "img": "https://basket-27.wbbasket.ru/vol4968/part496842/496842835/images/c516x688/2.webp",
  "product": "https://www.wildberries.ru/catalog/496842835/detail.aspx",
  "brand": "Befree",
  "name": "Пальто оверсайз длинное драповое с поясом",
  "id": 496842835,
  "crop": true
 },
 "office": {
  "img": "https://basket-34.wbbasket.ru/vol7339/part733931/733931454/images/c516x688/3.webp",
  "product": "https://www.wildberries.ru/catalog/733931454/detail.aspx",
  "brand": "Befree",
  "name": "Рубашка oversize с карманом",
  "id": 733931454,
  "crop": true
 },
 "smart": {
  "img": "https://basket-11.wbbasket.ru/vol1638/part163832/163832318/images/c516x688/3.webp",
  "product": "https://www.wildberries.ru/catalog/163832318/detail.aspx",
  "brand": "Befree",
  "name": "Пиджак оверсайз удлиненный классический школьный",
  "id": 163832318,
  "crop": true
 },
 "casual": {
  "img": "https://basket-31.wbbasket.ru/vol6177/part617773/617773455/images/c516x688/2.webp",
  "product": "https://www.wildberries.ru/catalog/617773455/detail.aspx",
  "brand": "Befree",
  "name": "Джинсы прямые классические со средней посадкой",
  "id": 617773455,
  "crop": true
 },
 "street": {
  "img": "https://basket-27.wbbasket.ru/vol4946/part494664/494664474/images/c516x688/2.webp",
  "product": "https://www.wildberries.ru/catalog/494664474/detail.aspx",
  "brand": "Befree",
  "name": "Худи-полузамок спортивная с капюшоном",
  "id": 494664474,
  "crop": true
 },
 "athleisure": {
  "img": "https://basket-16.wbbasket.ru/vol2500/part250024/250024746/images/c516x688/2.webp",
  "product": "https://www.wildberries.ru/catalog/250024746/detail.aspx",
  "brand": "calzedonia",
  "name": "Леггинсы из хлопка",
  "id": 250024746,
  "crop": true
 },
 "romantic": {
  "img": "https://basket-39.wbbasket.ru/vol8842/part884239/884239294/images/c516x688/3.webp",
  "product": "https://www.wildberries.ru/catalog/884239294/detail.aspx",
  "brand": "Befree",
  "name": "Платье асимметричное миди с принтом и кружевом летнее",
  "id": 884239294,
  "crop": true
 },
 "ballet": {
  "img": "https://basket-18.wbbasket.ru/vol2934/part293419/293419150/images/c516x688/2.webp",
  "product": "https://www.wildberries.ru/catalog/293419150/detail.aspx",
  "brand": "EKONIKA",
  "name": "Балетки Мэри Джейн",
  "id": 293419150,
  "crop": false
 },
 "black": {
  "img": "https://basket-32.wbbasket.ru/vol6500/part650062/650062407/images/c516x688/2.webp",
  "product": "https://www.wildberries.ru/catalog/650062407/detail.aspx",
  "brand": "Befree",
  "name": "Платье миди асимметричное из жатой ткани школьное",
  "id": 650062407,
  "crop": true
 },
 "grunge": {
  "img": "https://basket-38.wbbasket.ru/vol8637/part863738/863738755/images/c516x688/2.webp",
  "product": "https://www.wildberries.ru/catalog/863738755/detail.aspx",
  "brand": "Befree",
  "name": "Рубашка в клетку с присборенным нижним краем",
  "id": 863738755,
  "crop": true
 },
 "boho": {
  "img": "https://basket-41.wbbasket.ru/vol9877/part987765/987765743/images/c516x688/2.webp",
  "product": "https://www.wildberries.ru/catalog/987765743/detail.aspx",
  "brand": "Befree",
  "name": "Платье макси из хлопкового муслина с пышными рукавами летнее",
  "id": 987765743,
  "crop": true
 },
 "preppy": {
  "img": "https://basket-44.wbbasket.ru/vol12287/part1228714/1228714598/images/c516x688/2.webp",
  "product": "https://www.wildberries.ru/catalog/1228714598/detail.aspx",
  "brand": "Befree",
  "name": "Кардиган вязаный на пуговицах",
  "id": 1228714598,
  "crop": true
 },
 "denim": {
  "img": "https://basket-39.wbbasket.ru/vol8842/part884213/884213814/images/c516x688/1.webp",
  "product": "https://www.wildberries.ru/catalog/884213814/detail.aspx",
  "brand": "Befree",
  "name": "Куртка джинсовая укороченная с отложным воротником",
  "id": 884213814,
  "crop": true
 },
 "utility": {
  "img": "https://basket-25.wbbasket.ru/vol4550/part455048/455048771/images/c516x688/1.webp",
  "product": "https://www.wildberries.ru/catalog/455048771/detail.aspx",
  "brand": "Befree",
  "name": "Куртка стеганая с воротником-стойкой",
  "id": 455048771,
  "crop": true
 },
 "glam": {
  "img": "https://basket-29.wbbasket.ru/vol5608/part560832/560832925/images/c516x688/2.webp",
  "product": "https://www.wildberries.ru/catalog/560832925/detail.aspx",
  "brand": "Befree",
  "name": "Платье мини облегающее с пайетками",
  "id": 560832925,
  "crop": true
 }
}
