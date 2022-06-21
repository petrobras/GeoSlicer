# Skeleton [Do not change]

Esse modulo serve apenas como template para criação de novos módulos. Ele possui algumas definições que são usadas para fazer substituições via metaprogramação, para gerar novas classes. Portanto, nem sempre ele irá rodar sem erros no Slicer. Para testá-lo, gere um modulo a partir dele, com o comando abaixo:
```console
python new-module.py -n NomeDoNovoModulo [--bind]
```
o parametro "--bind" é opcional e somente necessário se você quer criar dentro do ambiente da LTrace, usando nossos Wrappers.