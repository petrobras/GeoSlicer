# Volume Calculator

_GeoSlicer_ module to do calculations with volumes, as described in the steps bellow:

1. In the _Formula_ field, type any mathematical expression using the volumes names inside braces { } (or double-clicking their names on the _Node_ area to do this automatically). For example, for two volumes _Volume1_ and _Volume2_, you could type:
    
    {Volume1} + log({Volume2})

    {Volume1} < 10000 (Returns 1 where the intensity value is less than 10000 and 0 elsewhere; i.e., a mask)

    ({Volume1} > 13000) * {Volume1} (Returns a mask and then multiplies by the volume intensity values to get the resulting volume from the mask)
   
2. If your volumes names are too big, you can also set mnemonics for them, to allow a more compact formula. Click the _Mnemonics_ group box, create a new _Mnemonic table_ and double-click the table cells to edit the values for the _Volume name_ and its _Mnemonic_. You can add more entries or remove them by clicking _Add mnemonic_ and _Remove selected mnemonics_ respectively. The mnemonics tables will be saved on the scene under the _Volume Calculator Mnemonics_ directory, to allow their use in other calculations. By selecting a mnemonic table before entering a formula, double-clicking the volumes will automatically add their mnemonics to the formula.
    
2. Enter an _Output volume name_ (just the name, without braces);

3. Click the _Calculate_ button and wait for completion. If a new volume is created as output, it will be located at the same directory as the first volume in the formula;