const yaml_fields = [
    'security.authentication.type'
];

module.exports = (on, config) => {
        
    const fs = require('fs');
    const _ = require('lodash');
    const yaml = require('js-yaml');

    let new_config = {};

    try {
  
        let fileContents = fs.readFileSync(process.env.QHUB_CONFIG_PATH, 'utf8');
        let data = yaml.load(fileContents);

        console.log(data);

        new_config['env'] = _.fromPairs(
                _.map(yaml_fields, 
                    field => ['qhub_'+field.replace(/\./g, '_') , _.get(data, field, '')]
                        )
        );

    }
    catch (e) {
        console.log(e);
    }

    return new_config;
  };

  