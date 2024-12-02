import qt
import slicer
from dataclasses import dataclass
from ltrace.slicer.helpers import listLtraceModules, openModuleHelp


@dataclass
class EnvModule:
    cls: object
    name: str
    tag: str
    clsObject: object
    modules: list


class ModulesHelpMenu(qt.QMenu):
    def __init__(self, ltrace_icon_path, *args, **kwargs):
        super().__init__("LTrace modules", *args, **kwargs)
        self.__menuList = list()
        self.__actionList = list()
        self.__ltrace_icon_path = ltrace_icon_path
        self.__setup()

    def __setup(self):
        """Setup menu widget

        Returns:
            [type]: [description]
        """
        self.setIcon(qt.QIcon(str(self.__ltrace_icon_path)))
        ltraceModules = listLtraceModules(sort=True)

        # Filter modules/environments
        envList = self.__getEnvironments()
        moduleToRemove = list()
        for module in ltraceModules:
            for env in envList:
                if env.name == module.parent.title:
                    env.clsObject = module
                    moduleToRemove.append(module)
                    break

                if env.tag in module.parent.title:
                    moduleToRemove.append(module)
                    break

        for module in moduleToRemove:
            ltraceModules.remove(module)

        # Create 'others' environment
        otherEnv = EnvModule(cls=None, name="Others", tag=None, clsObject=None, modules=ltraceModules)
        envList.append(otherEnv)

        for env in envList:
            if env.clsObject is None:  # Others
                menu = qt.QMenu(env.name)
                self.__menuList.append(menu)

                for module in env.modules:
                    menu.addAction(self.__createModuleAction(module))

                self.addMenu(menu)

            else:  # Environments
                self.addAction(self.__createModuleAction(env.clsObject))

    def __getEnvironments(self):
        """Retrieve the environments plugin data

        Returns:
            list: A list cointaining the environments plugin data
        """
        try:
            core = EnvModule(
                cls=slicer.modules.coreenv, name=slicer.modules.coreenv.title, tag="Core", clsObject=None, modules=[]
            )
            imageLog = EnvModule(
                cls=slicer.modules.imagelogenv,
                name=slicer.modules.imagelogenv.title,
                tag="Image Log",
                clsObject=None,
                modules=[],
            )
            microCt = EnvModule(
                cls=slicer.modules.microctenv,
                name=slicer.modules.microctenv.title,
                tag="Micro CT",
                clsObject=None,
                modules=[],
            )
            thinSection = EnvModule(
                cls=slicer.modules.thinsectionenv,
                name=slicer.modules.thinsectionenv.title,
                tag="Thin Section",
                clsObject=None,
                modules=[],
            )
            multiScale = EnvModule(
                cls=slicer.modules.multiscaleenv,
                name=slicer.modules.multiscaleenv.title,
                tag="Multiscale",
                clsObject=None,
                modules=[],
            )

            return [core, imageLog, microCt, thinSection, multiScale]

        except AttributeError:
            return []

    def __createModuleAction(self, module):
        """Wrapper for QAction creation..

        Args:
            module (ScriptedLoadableModule.ScriptedLoadableModule): the module object

        Returns:
            qt.QAction: The QAction's object
        """
        action = qt.QAction(qt.QIcon(module.parent.icon), module.parent.title)
        action.triggered.connect(lambda state, x=module: openModuleHelp(x))
        self.__actionList.append(action)
        return action
