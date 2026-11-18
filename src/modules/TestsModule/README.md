# TestsModule

This module implements tests for code that do not belong to other modules.

All test implementations must be done as methods in TestsModuleLogic, using
the @newTest decorator.

## Example

```sh
class TestsModuleLogic(LTracePluginLogic):

    ...
    
    @newTest(title="Test 1", tooltip="This is my first test")
    def myFirstTest(self):
        '''
        Test description
        '''
        # run test logic
        passed = True
        return passed

    @newTest(title="Test 2", tooltip="This is my first test")
    def mySecondTest(self):
       '''
       Test description
       '''
       # run test logic
       passed = False
       return passed

    @newTest(title="Test 3", tooltip="This is my third test")
    def myThirdTest(self):
        '''
        Test description
        '''
        # run test logic
        passed = True
        return passed
    
    ...
```