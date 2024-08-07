def util = [:]

pipeline {
    agent any
    parameters {
        booleanParam(name: 'STATIC_ANALISYS', defaultValue: true, description: 'Allow to run the code static analysis process')
        booleanParam(name: 'UNIT_TESTS', defaultValue: true, description: 'Allow to run the unit test process')
        booleanParam(name: 'INTEGRATION_TESTS', defaultValue: true, description: 'Allow to run the integration test process')
        booleanParam(name: 'EXPORT', defaultValue: false, description: 'Allow to export the generated application to the OCI bucket')
        booleanParam(name: 'SFX', defaultValue: false, description: 'Create Self-Extracting File instead of the compressed file')
        booleanParam(name: 'PUBLIC_VERSION', defaultValue: false, description: 'Generate the application\'s public version. The commit to the opensource code will be ignored.')
        choice(name: 'PLATFORM', choices: ['Linux', 'Windows'], description: 'Select the desired Operational System to generate the application.')
        string(name: 'BASE', defaultValue: 'latest', description: 'Filename of the base archive or version number. "latest" will download the latest version from the OCI bucket.')
        choice(name: 'MODE', choices: ['Production', 'Development'], description: 'Select the desired application\'s mode to export')
    }
    options {
            skipDefaultCheckout() 
            throttle(['test'])
    }
    environment {
        OCI_DOCKER_REGISTRY_TOKEN_ID     = credentials("oci_docker_registry_token_id")
        OCI_DOCKER_REGISTRY_TOKEN_PASSWORD = credentials("oci_docker_registry_token_password")
    }
    triggers {
        cron "H 13 * * *"
    }
    stages {
        stage('Start') {
            options {
                skipDefaultCheckout()
            }
            when {
                beforeAgent true;
                anyOf {
                    triggeredBy cause: 'UserIdCause'
                    triggeredBy cause: 'TimerTrigger'
                    triggeredBy cause: 'SCMTrigger'
                }
            }
            failFast true
            stages {
                stage("Windows") {
                    when { 
                        beforeAgent true;
                        allOf {
                                expression { return "${params.PLATFORM}" == "Windows"; }
                                triggeredBy cause: 'UserIdCause'
                        }
                    }
                    agent {
                            label "windows"
                    }
                    options { skipDefaultCheckout() }
                    environment {
                        PIP_DEFAULT_TIMEOUT = 300
                    }
                    stages {
                        stage('Build [Windows]') {
                            options {
                                skipDefaultCheckout()
                                timeout(time: 120, unit: "MINUTES")
                            }
                            steps {
                                cleanWs()
                                checkout scm

                                script {
                                    def rootDir = pwd()
                                    util = load "${rootDir}/tools/jenkins/util.groovy"

                                    if (params.STATIC_ANALISYS == true || params.UNIT_TESTS == true) {
                                        def id = "${env:OCI_DOCKER_REGISTRY_TOKEN_ID}"
                                        def psw = "${env:OCI_DOCKER_REGISTRY_TOKEN_PASSWORD}"
                                        util = load "${rootDir}/tools/jenkins/util.groovy"
                                        util.login_docker_oci_registry(id, psw)
                                        util.build_docker()
                                    }
                                    
                                }
                            }
                            post {
                                always {
                                        script {
                                            util.run_docker_prune()
                                    }
                                }
                            }
                        }
                        stage('Static Analysis [Windows]') {
                            options {
                                timeout(time: 5, unit: "MINUTES")
                            }
                            when { 
                                anyOf {
                                        expression { return "${params.STATIC_ANALISYS}" == "true"; }
                                }
                            }
                            steps {
                                script {
                                    util.run_static_analysis_process()
                                }
                            }
                        }
                        stage('Run Unit Test [Windows]') {
                            options {
                                timeout(time: 20, unit: "MINUTES")
                            }
                            when { 
                                anyOf {
                                        expression { return "${params.UNIT_TESTS}" == "true"; }
                                }
                            }
                            steps {
                                script {
                                    util.run_unit_test_process()
                                }
                            }
                        }
                        stage('Generate & Test & Export [Windows]') {
                            options {
                                timeout(time: 600, unit: "MINUTES")
                            }
                            when {
                                anyOf {
                                        expression { return "${params.EXPORT}" == "true"; }
                                        expression { return "${params.INTEGRATION_TESTS}" == "true"; }
                                }
                            }
                            steps {
                                script {
                                    Random rnd = new Random()
                                    def version = "v${rnd.nextInt(9)}.${rnd.nextInt(9)}${rnd.nextInt(9)}"
                                    def no_test_flag = ("${params.EXPORT}" == "false") ? "--no-export" : ""
                                    def no_export_flag = ("${params.INTEGRATION_TESTS}" == "false") ? "--no-test" : ""
                                    def sfx_flag = ("${params.SFX}" == "true") ? "--sfx" : ""                                    
                                    def prod_flag = ("${params.MODE}" == "Production") ? "--production" : ""
                                    def public_flag = ("${params.PUBLIC_VERSION}" == "true") ? "--generate-public-version --no-public-commit" : ""
                                    def base = "${params.BASE}"
                                    if (base.trim().isEmpty()) {
                                        error("Base is empty. Please, set the base parameter.")
                                    }
                                    def arguments = "--version ${version} --no-gpu ${no_test_flag} --base ${base} ${no_export_flag} ${sfx_flag} ${prod_flag} ${public_flag}"
                                    util.download_and_deploy(arguments, false)
                                    if (params.EXPORT == true) {                                        
                                        def file_name = util.get_exported_application_name(params.MODE, version)
                                        println("Application package exported as ${file_name}.")
                                    }
                                }
                            }
                        }
                    }
                    post {
                        // Clean after build
                        always {
                            cleanWs(cleanWhenNotBuilt: false,
                                    deleteDirs: true,
                                    disableDeferredWipeout: true,
                                    notFailBuild: true,
                                    patterns: [[pattern: '.gitignore', type: 'INCLUDE'],
                                            [pattern: '.propsfile', type: 'EXCLUDE']])
                        }
                    }
                }
                stage("Linux") {
                    when { 
                        beforeAgent true;
                        anyOf {
                                allOf {
                                    expression { return "${params.PLATFORM}" == "Linux"; }                                    
                                    triggeredBy cause: 'UserIdCause'
                                }
                                allOf {
                                    anyOf {
                                        expression { return "${BRANCH_NAME}" == "develop"; }
                                        // expression { return "${BRANCH_NAME}".contains("release")}
                                    }
                                    anyOf {
                                        triggeredBy cause: 'TimerTrigger'
                                        triggeredBy cause: 'SCMTrigger'
                                    }
                                }
                        }
                    }          
                    agent {
                            label "linux"
                    }
                    options { skipDefaultCheckout() }
                    environment {
                        PIP_DEFAULT_TIMEOUT = 300
                    }
                    stages {
                        stage('Build [Linux]') {
                            options {
                                timeout(time: 90, unit: "MINUTES")
                            }
                            steps {
                                cleanWs()
                                checkout scm
                                script {
                                    def rootDir = pwd()
                                    def id = "${OCI_DOCKER_REGISTRY_TOKEN_ID}"
                                    def psw = "${OCI_DOCKER_REGISTRY_TOKEN_PASSWORD}"
                                    util = load "${rootDir}/tools/jenkins/util.groovy"
                                    util.login_docker_oci_registry(id, psw)
                                    util.build_docker()
                                }
                            }
                            post {
                                always {
                                    script {
                                        util.run_docker_prune()                          
                                    }
                                }
                            }
                        }
                        stage('Static Analysis [Linux]') {
                            options {
                                timeout(time: 5, unit: "MINUTES")
                            }
                            when { 
                                anyOf {
                                        expression { return "${params.STATIC_ANALISYS}" == "true"; }
                                }
                            }
                            steps {
                                script {
                                    util.run_static_analysis_process()
                                }
                            }
                        }
                        stage('Run Unit Test [Linux]') {
                            options {
                                timeout(time: 20, unit: "MINUTES")
                            }
                            when { 
                                anyOf {
                                        expression { return "${params.UNIT_TESTS}" == "true"; }
                                }
                            }
                            steps {
                                script {
                                    util.run_unit_test_process()
                                }
                            }
                        }
                        stage('Generate & Test & Export [Linux]') {
                            when {
                                anyOf {
                                        expression { return "${params.EXPORT}" == "true"; }
                                        expression { return "${params.INTEGRATION_TESTS}" == "true"; }
                                }
                            }
                            steps {
                                script {
                                    Random rnd = new Random()
                                    def version = "v${rnd.nextInt(9)}.${rnd.nextInt(9)}${rnd.nextInt(9)}"
                                    def no_test_flag = ("${params.EXPORT}" == "false") ? "--no-export" : ""
                                    def no_export_flag = ("${params.INTEGRATION_TESTS}" == "false") ? "--no-test" : ""
                                    def sfx_flag = ("${params.SFX}" == "true") ? "--sfx" : ""
                                    def prod_flag = ("${params.MODE}" == "Production") ? "--production" : ""
                                    def public_flag = ("${params.PUBLIC_VERSION}" == "true") ? "--generate-public-version --no-public-commit" : ""
                                    def base = "${params.BASE}"
                                    if (base.trim().isEmpty()) {
                                        error("Base is empty. Please, set the base parameter.")
                                    }
                                    def arguments = "--version ${version} --no-gpu ${no_test_flag} --base ${base} ${no_export_flag} ${sfx_flag} ${prod_flag} ${public_flag}"
                                    util.download_and_deploy(arguments, true)
                                    if (params.EXPORT == true) {
                                        def file_name = util.get_exported_application_name(params.MODE, version)
                                        println("Application package exported as ${file_name}.")
                                    }
                                }
                            }
                            post {
                                always {
                                    script {
                                        util.docker_compose_down()
                                    }
                                }
                            }
                        }
                    }
                    post {
                        // Clean after build
                        always {
                            cleanWs(cleanWhenNotBuilt: false,
                                    deleteDirs: true,
                                    disableDeferredWipeout: true,
                                    notFailBuild: true,
                                    patterns: [[pattern: '.gitignore', type: 'INCLUDE'],
                                            [pattern: '.propsfile', type: 'EXCLUDE']])
                        }
                    }
                }
            }
        }
        /*
        stage('Run UI Test') {
            agent { node { label 'ui_test_node' }}
            options {
                skipDefaultCheckout()
                throttle(['ui_test'])
                timeout(time: 2, unit: 'HOURS')
            }
            when {
                beforeAgent true;
                allOf {
                    anyOf {
                        expression { return "${BRANCH_NAME}" == "develop" }
                        expression { return "${BRANCH_NAME}".contains("release")}
                    }
                }
            }
            steps {
                script {
                    cleanWs()
                    checkout scm
                    def rootDir = pwd()
                    util = load "${rootDir}/tools/jenkins/util.groovy"           
                }
                script {
                    catchError(buildResult: 'SUCCESS', stageResult: 'FAILURE') {
                        Random rnd = new Random()
                        def version = "v${rnd.nextInt(9)}.${rnd.nextInt(9)}${rnd.nextInt(9)}"
                        def sikulix_branch = ("${BRANCH_NAME}".contains("release")) ? "release" : "develop"
                        def base = "${params.BASE}"
                        if (base.trim().isEmpty()) {
                            error("Base is empty. Please, set the base parameter.")
                        }
                        def arguments = "--version ${version} --base ${base} --no-export --no-test --test-ui --sikulix-branch jenkins_sikulix"
                        util.execute_ui_test(arguments)
                    }
                }
            }
            post {
                // Clean after build
                always {
                    cleanWs(cleanWhenNotBuilt: false,
                            deleteDirs: true,
                            disableDeferredWipeout: true,
                            notFailBuild: true,
                            patterns: [[pattern: '.gitignore', type: 'INCLUDE'],
                                    [pattern: '.propsfile', type: 'EXCLUDE']])
                }
            }
        }
        */
    }
    post {
        failure {
            script {
                if (currentBuild.getBuildCauses('hudson.triggers.TimerTrigger$TimerTriggerCause') && "${BRANCH_NAME}" == "develop") {
                    echo "Sending slack notification"
                    def message = "⚠️ Daily test run on *${BRANCH_NAME}* failed. <${env.BUILD_URL}console|Console Output>"
                    def url = '''"$SLACK_WEBHOOK"'''
                    withCredentials([string(credentialsId: 'slack_webhook', variable: 'SLACK_WEBHOOK')]) {
                        util.notify_slack(message, url)
                    }
                }
            }
        }
    }
}