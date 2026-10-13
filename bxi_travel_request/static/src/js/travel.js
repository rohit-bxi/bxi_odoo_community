console.log("JS Loaded");

function initStateBinding() {

    function bind(countryId, stateId) {
        var country = document.getElementById(countryId);
        var state = document.getElementById(stateId);

        console.log("Binding:", countryId, country);
        if (!country || !state) return;

        country.addEventListener("change", function () {

            var countryIdVal = this.value;

            console.log("Selected country:", countryIdVal);

            fetch('/my/submit-travel-request?country_id=' + countryIdVal)
            .then(res => res.json())
            .then(data => {

                state.innerHTML = '<option value="">Select State</option>';

                data.states.forEach(function (s) {
                    var option = document.createElement("option");
                    option.value = s.id;
                    option.text = s.name;
                    state.appendChild(option);
                });

            });

        });
    }

    bind("from_country", "from_state");
    bind("to_country", "to_state");
}
setTimeout(initStateBinding, 1000);