export const languages = [
  ['ro', 'Română'], ['en', 'Engleză'], ['de', 'Germană'], ['fr', 'Franceză'],
  ['it', 'Italiană'], ['es', 'Spaniolă'], ['pl', 'Poloneză'], ['cs', 'Cehă'],
  ['hu', 'Maghiară'], ['tr', 'Turcă'], ['bg', 'Bulgară'],
  ['zh-CN', 'Chineză simplificată · China'], ['zh-TW', 'Chineză tradițională · Taiwan'],
  ['ja', 'Japoneză'], ['ko', 'Coreeană'], ['pt', 'Portugheză'], ['nl', 'Neerlandeză'],
  ['el', 'Greacă'], ['sk', 'Slovacă'], ['sl', 'Slovenă'], ['hr', 'Croată'],
  ['sr', 'Sârbă'], ['uk', 'Ucraineană'], ['sv', 'Suedeză'], ['da', 'Daneză'],
  ['no', 'Norvegiană'], ['fi', 'Finlandeză'],
];

export const units = [
  ['pcs', 'Bucăți'], ['BUC', 'Bucăți · cod RO'], ['set', 'Set'], ['pair', 'Pereche'],
  ['kit', 'Kit'], ['box', 'Cutie'], ['pack', 'Pachet'], ['roll', 'Rolă'],
  ['pallet', 'Palet'], ['kg', 'Kilogram'], ['g', 'Gram'], ['t', 'Tonă'],
  ['m', 'Metru'], ['cm', 'Centimetru'], ['mm', 'Milimetru'], ['m2', 'Metru pătrat'],
  ['m3', 'Metru cub'], ['l', 'Litru'], ['ml', 'Mililitru'], ['h', 'Oră'],
];

export const currencies = [
  ['EUR', 'EUR · Euro'], ['RON', 'RON · Leu românesc'], ['USD', 'USD · Dolar SUA'],
  ['CNY', 'CNY · Yuan chinezesc (RMB)'], ['GBP', 'GBP · Liră sterlină'],
  ['CHF', 'CHF · Franc elvețian'], ['JPY', 'JPY · Yen japonez'], ['KRW', 'KRW · Won sud-coreean'],
  ['HKD', 'HKD · Dolar Hong Kong'], ['SGD', 'SGD · Dolar Singapore'],
  ['PLN', 'PLN · Zlot polonez'], ['CZK', 'CZK · Coroană cehă'], ['HUF', 'HUF · Forint maghiar'],
  ['SEK', 'SEK · Coroană suedeză'], ['NOK', 'NOK · Coroană norvegiană'],
  ['DKK', 'DKK · Coroană daneză'], ['TRY', 'TRY · Liră turcească'],
  ['CAD', 'CAD · Dolar canadian'], ['AUD', 'AUD · Dolar australian'],
  ['INR', 'INR · Rupie indiană'], ['AED', 'AED · Dirham EAU'], ['ZAR', 'ZAR · Rand sud-african'],
];

// Keep historical invoice currencies selectable even when absent from the suggestions.
export const currencyOptions = value => currencies.some(([code]) => code === value)
  ? currencies : [...currencies, [value, value]];
