def util = [:]

pipeline {
    agent none
    options {
            skipDefaultCheckout() 
            throttle(['development'])
            }
    environment {
        OCI_DOCKER_REGISTRY_TOKEN_ID     = credentials("oci_docker_registry_token_id")
        OCI_DOCKER_REGISTRY_TOKEN_PASSWORD = credentials("oci_docker_registry_token_password")
    }
    stages {
        stage("Start") {
            agent any
            options { 
                skipDefaultCheckout() 
            }
            when {
                beforeAgent true;
                anyOf {
                    triggeredBy cause: 'UserIdCause'
                    changeRequest()
                }
            }
            environment {
                PIP_DEFAULT_TIMEOUT = 300
            }
            stages {
                stage('Build') {
                    options {
                        timeout(time: 120, unit: "MINUTES")
                    }
                    steps {
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
                stage('Static Analysis') {
                    options {
                        timeout(time: 5, unit: "MINUTES")
                    }
                    steps {
                        script {
                            util.run_static_analysis_process()
                        }
                    }
                }
                stage('Run Unit Test') {
                    options {
                        timeout(time: 20, unit: "MINUTES")
                    }
                    steps {
                        script {
                            util.run_unit_test_process()
                        }
                    }
                }
            }
        }
    }
}
